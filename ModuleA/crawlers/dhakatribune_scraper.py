"""
Real scraper for Dhaka Tribune (dhakatribune.com) using Selenium.
Scrapes actual articles from the website (no dummy data).

URL pattern: https://www.dhakatribune.com/{category}/{article_id}/{slug}

Usage:
    python dhakatribune_scraper.py --limit 500 --output-dir ./scraped_data
"""

import argparse
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Set
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class Article:
    """Represents a news article."""
    url: str
    title: str
    body: str
    date: Optional[str]
    language: str
    source: str
    category: str
    tokens: int = 0
    named_entities: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    crawled_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    def __post_init__(self):
        if self.tokens == 0 and self.body:
            self.tokens = len(self.body.split())
    
    def is_valid(self) -> bool:
        return bool(
            self.url and 
            self.title and 
            self.body and 
            len(self.body) > 100
        )
    
    def to_dict(self) -> dict:
        return asdict(self)


class SeleniumBrowserClient:
    """Browser client using Selenium for dynamic content."""
    
    def __init__(self, headless: bool = True, delay: float = 0.6):
        self.headless = headless
        self.delay = delay
        self.last_request_time = 0.0
        self.driver = self._init_driver()
    
    def _init_driver(self):
        """Initialize Chrome WebDriver with anti-detection measures."""
        try:
            chrome_options = Options()
            if self.headless:
                chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)
            chrome_options.add_argument(
                "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            
            # Hide webdriver
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            })
            
            logger.info("Selenium WebDriver initialized successfully")
            return driver
        except Exception as e:
            logger.error(f"Failed to initialize WebDriver: {e}")
            return None
    
    def _rate_limit(self):
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
    
    def _reset_driver(self):
        """Reset the WebDriver."""
        try:
            if self.driver:
                self.driver.quit()
        except:
            pass
        self.driver = self._init_driver()
    
    def get(self, url: str, retries: int = 2) -> Optional[str]:
        """Fetch URL using browser with retry logic."""
        if not self.driver:
            self._reset_driver()
        
        for attempt in range(retries):
            self._rate_limit()
            
            try:
                logger.debug(f"Fetching: {url} (attempt {attempt + 1})")
                self.driver.get(url)
                time.sleep(0.5)  # Wait for JS rendering (reduced from 1)
                self.last_request_time = time.time()
                return self.driver.page_source
            except Exception as e:
                logger.debug(f"Error fetching {url} (attempt {attempt + 1}): {e}")
                if attempt < retries - 1:
                    time.sleep(1)  # Wait before retry (reduced from 2)
                    # Try to reset driver if connection error
                    if "connection" in str(e).lower() or "closed" in str(e).lower():
                        logger.info("Connection lost, resetting WebDriver...")
                        self._reset_driver()
                self.last_request_time = time.time()
        
        logger.warning(f"Failed to fetch {url} after {retries} attempts")
        return None
    
    def close(self):
        """Close browser."""
        if self.driver:
            self.driver.quit()


class DhakaTribuneScraper:
    """Scraper for Dhaka Tribune (dhakatribune.com) using Selenium."""
    
    SOURCE_NAME = "dhaka_tribune"
    LANGUAGE = "en"
    BASE_URL = "https://www.dhakatribune.com"
    
    # Categories from the website
    CATEGORIES = [
        "bangladesh/politics",
        "bangladesh/nation",
        "business",
        "sport",
        "world",
        "opinion",
        "feature",
        "entertainment",
        "lifestyle",
        "science-tech",
    ]
    
    def __init__(self, browser: Optional[SeleniumBrowserClient] = None):
        self.browser = browser or SeleniumBrowserClient()
        self.articles: List[Article] = []
        self._seen_urls: Set[str] = set()
        self.articles_per_category = 50  # Will adjust based on limit
    
    def scrape(self, limit: int = 500) -> int:
        """Scrape articles from Dhaka Tribune."""
        logger.info(f"[{self.SOURCE_NAME}] Starting scrape (target: {limit} articles)")
        
        # Calculate articles needed per category with buffer
        # Using more categories and pages to ensure we hit target
        articles_per_category = max(1, (limit // len(self.CATEGORIES)) + 30)
        self.articles_per_category = articles_per_category
        
        for category in self.CATEGORIES:
            if len(self.articles) >= limit:
                break
            
            logger.info(f"[{self.SOURCE_NAME}] Scraping category: {category}")
            category_count = 0
            consecutive_failures = 0
            
            # Try many pages for each category to collect more articles
            for page in range(150):  # Increased from 100 to 150
                if category_count >= articles_per_category or len(self.articles) >= limit:
                    break
                
                # Stop if we have too many consecutive failures
                if consecutive_failures >= 3:  # Reduced from 5 to 3 - be faster
                    logger.debug(f"[{self.SOURCE_NAME}] Too many failures in {category}, moving to next category")
                    break
                
                # Build category URL - Dhaka Tribune uses /{category} for listing
                if page == 0:
                    category_url = f"{self.BASE_URL}/{category}"
                else:
                    category_url = f"{self.BASE_URL}/{category}?page={page}"
                
                html = self.browser.get(category_url, retries=2)
                if not html:
                    consecutive_failures += 1
                    logger.debug(f"Failed to fetch {category_url}, trying next page... (failures: {consecutive_failures})")
                    time.sleep(1)
                    continue
                
                consecutive_failures = 0
                
                # Extract article links from category page
                article_urls = self._extract_article_urls(html)
                
                if not article_urls:
                    logger.debug(f"No articles found on page {page} of {category}, stopping pagination")
                    break  # Stop if no URLs found
                
                logger.info(f"[{self.SOURCE_NAME}] Found {len(article_urls)} article URLs on page {page}")
                
                # Scrape each article
                for article_url in article_urls:
                    if category_count >= articles_per_category or len(self.articles) >= limit:
                        break
                    
                    if article_url in self._seen_urls:
                        continue
                    
                    self._seen_urls.add(article_url)
                    
                    html = self.browser.get(article_url, retries=1)
                    if not html:
                        continue
                    
                    article = self._parse_article(article_url, html, category)
                    if article and article.is_valid():
                        self.articles.append(article)
                        category_count += 1
                        logger.info(
                            f"[{self.SOURCE_NAME}] [{len(self.articles)}/{limit}] "
                            f"{article.title[:70]}..."
                        )
        
        logger.info(f"[{self.SOURCE_NAME}] Complete. Total: {len(self.articles)} articles")
        return len(self.articles)
    
    def _extract_article_urls(self, html: str) -> List[str]:
        """Extract article URLs from category listing page.
        
        Dhaka Tribune URL pattern: /{category}/{article_id}/{slug}
        Example: /bangladesh/politics/4245/article-title
        """
        urls = []
        try:
            soup = BeautifulSoup(html, "lxml")
            links = soup.find_all("a", href=True)
            
            for link in links:
                href = link.get("href", "").strip()
                
                if not href or href.startswith("#") or href.startswith("http"):
                    continue
                
                # Remove query parameters
                href_clean = href.split('?')[0]
                
                # Match pattern: /{category}/{numeric_id}/{slug}
                # Must have numeric ID in the path
                if re.search(r"/\d{3,}/", href_clean) and "/video/" not in href_clean.lower():
                    full_url = urljoin(self.BASE_URL, href_clean)
                    if full_url not in self._seen_urls and full_url not in urls:
                        urls.append(full_url)
        
        except Exception as e:
            logger.error(f"Error extracting article URLs: {e}")
        
        return urls
    
    def _parse_article(self, url: str, html: str, category: str) -> Optional[Article]:
        """Parse article content from HTML."""
        try:
            soup = BeautifulSoup(html, "lxml")
            
            # Extract title
            title = None
            for selector in ["h1", "h1.post-title", "meta[property='og:title']"]:
                elem = soup.select_one(selector)
                if elem:
                    if selector.startswith("meta"):
                        title = elem.get("content", "").strip()
                    else:
                        title = elem.get_text(strip=True)
                    if title and len(title) > 10:
                        break
            
            if not title or len(title) < 10:
                return None
            
            # Extract body text from article containers
            body_parts = []
            for selector in [
                "div.story-body",
                "article",
                "div.article-content",
                "div.post-content",
                "div[class*='story']",
                "div[class*='content']"
            ]:
                container = soup.select_one(selector)
                if container:
                    paragraphs = container.find_all("p")
                    for p in paragraphs:
                        text = p.get_text(strip=True)
                        # Filter out scripts, ads, and short text
                        if text and len(text) > 20 and not text.startswith("var ") and not text.startswith("function"):
                            body_parts.append(text)
                    if body_parts:
                        break
            
            # Fallback: collect all meaningful paragraphs
            if not body_parts:
                for p in soup.find_all("p"):
                    text = p.get_text(strip=True)
                    if text and len(text) > 20 and not text.startswith("var ") and not text.startswith("function"):
                        body_parts.append(text)
            
            body = "\n\n".join(body_parts)
            
            # Validate body length
            if len(body) < 100:
                return None
            
            # Extract date
            date = None
            
            # Try time element
            time_elem = soup.select_one("time")
            if time_elem:
                date = time_elem.get("datetime") or time_elem.get_text(strip=True)
            
            # Try meta tags
            if not date:
                meta = soup.select_one("meta[property='article:published_time']")
                if meta:
                    date = meta.get("content")
            
            if not date:
                meta = soup.select_one("meta[property='og:article:published_time']")
                if meta:
                    date = meta.get("content")
            
            article = Article(
                url=url,
                title=title,
                body=body,
                date=date,
                language=self.LANGUAGE,
                source=self.SOURCE_NAME,
                category=category,
            )
            
            return article if article.is_valid() else None
        
        except Exception as e:
            logger.error(f"Error parsing {url}: {e}")
            return None


def save_to_json(articles: List[Article], output_file: Path) -> None:
    """Save articles to JSON."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    articles_data = [a.to_dict() for a in articles]
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(articles_data, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved {len(articles_data)} articles to {output_file}")


def save_summary(articles: List[Article], output_file: Path) -> None:
    """Save summary statistics."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    summary = {
        "total_articles": len(articles),
        "scrape_timestamp": datetime.utcnow().isoformat(),
        "by_source": {},
        "by_category": {},
        "by_language": {},
        "average_tokens_per_article": 0,
        "content_statistics": {
            "min_tokens": 0,
            "max_tokens": 0,
            "avg_tokens": 0,
        },
        "date_coverage": {
            "articles_with_dates": 0,
            "articles_without_dates": 0
        }
    }
    
    total_tokens = 0
    dates_count = 0
    token_values = []
    
    for article in articles:
        if article.source not in summary["by_source"]:
            summary["by_source"][article.source] = 0
        summary["by_source"][article.source] += 1
        
        if article.category not in summary["by_category"]:
            summary["by_category"][article.category] = 0
        summary["by_category"][article.category] += 1
        
        if article.language not in summary["by_language"]:
            summary["by_language"][article.language] = 0
        summary["by_language"][article.language] += 1
        
        total_tokens += article.tokens
        token_values.append(article.tokens)
        
        if article.date:
            dates_count += 1
    
    if articles:
        summary["average_tokens_per_article"] = round(total_tokens / len(articles), 2)
        summary["date_coverage"]["articles_with_dates"] = dates_count
        summary["date_coverage"]["articles_without_dates"] = len(articles) - dates_count
        summary["content_statistics"]["min_tokens"] = min(token_values) if token_values else 0
        summary["content_statistics"]["max_tokens"] = max(token_values) if token_values else 0
        summary["content_statistics"]["avg_tokens"] = summary["average_tokens_per_article"]
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Saved summary to {output_file}")
    
    # Print summary to console
    logger.info("\n" + "="*80)
    logger.info("SCRAPING SUMMARY - DHAKA TRIBUNE")
    logger.info("="*80)
    logger.info(f"Total articles: {summary['total_articles']}")
    logger.info(f"Articles with dates: {summary['date_coverage']['articles_with_dates']}")
    logger.info(f"Articles without dates: {summary['date_coverage']['articles_without_dates']}")
    logger.info(f"Average tokens per article: {summary['average_tokens_per_article']}")
    logger.info(f"Min tokens: {summary['content_statistics']['min_tokens']}")
    logger.info(f"Max tokens: {summary['content_statistics']['max_tokens']}")
    logger.info("\nBy Category:")
    for cat, count in sorted(summary["by_category"].items(), key=lambda x: x[1], reverse=True):
        logger.info(f"  {cat}: {count}")
    logger.info("="*80 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Scrape REAL articles from Dhaka Tribune (dhakatribune.com)"
    )
    parser.add_argument("--limit", type=int, default=500, help="Target number of articles")
    parser.add_argument("--output-dir", type=Path, default=Path("scraped_data"), help="Output directory")
    parser.add_argument("--headless", action="store_true", default=True, help="Run in headless mode")
    
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    
    browser = SeleniumBrowserClient(headless=args.headless, delay=1.5)
    
    try:
        logger.info("="*80)
        logger.info(f"Starting Dhaka Tribune Scraper (Target: {args.limit} articles)")
        logger.info("="*80)
        
        scraper = DhakaTribuneScraper(browser=browser)
        scraped_count = scraper.scrape(limit=args.limit)
        
        if scraper.articles:
            # Save to JSON
            output_file = args.output_dir / "dhakatribune_articles.json"
            save_to_json(scraper.articles, output_file)
            
            # Save summary
            summary_file = args.output_dir / "dhakatribune_summary.json"
            save_summary(scraper.articles, summary_file)
            
            logger.info(f"\n✅ Successfully scraped {scraped_count} REAL articles from Dhaka Tribune")
            logger.info(f"📁 Output saved to: {output_file}")
            logger.info(f"📊 Summary saved to: {summary_file}")
        else:
            logger.warning("No articles were scraped")
    
    except Exception as e:
        logger.error(f"Scraping failed: {e}", exc_info=True)
    
    finally:
        browser.close()


if __name__ == "__main__":
    main()
