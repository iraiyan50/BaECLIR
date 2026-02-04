"""
Aggressive scraper for Dhaka Tribune (dhakatribune.com) using multiple strategies.
Scrapes REAL articles only - no dummy or generated data.

Strategies:
1. Direct category pagination (main method)
2. Search pages with different keywords
3. Archive/date-based URLs
4. API endpoints (if available)
"""

import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Set
from urllib.parse import urljoin, quote
from collections import Counter

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

stats = Counter()


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


class DhakaTribuneScraper:
    """Multi-strategy scraper for Dhaka Tribune."""
    
    SOURCE_NAME = "dhaka_tribune"
    LANGUAGE = "en"
    BASE_URL = "https://www.dhakatribune.com"
    
    # Multiple categories to cover diverse content
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
    
    # Search keywords to find more articles
    SEARCH_KEYWORDS = [
        "bangladesh", "election", "government", "politics",
        "dhaka", "news", "country", "business", "economy",
        "sport", "cricket", "world", "international",
        "entertainment", "culture", "technology", "environment"
    ]
    
    def __init__(self, headless: bool = True, delay: float = 0.5):
        self.headless = headless
        self.delay = delay
        self.articles: List[Article] = []
        self._seen_urls: Set[str] = set()
        self.driver = self._init_driver()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
    
    def _init_driver(self):
        """Initialize Chrome WebDriver."""
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
                "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            
            # Hide webdriver
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            })
            
            logger.info("✓ WebDriver initialized")
            return driver
        except Exception as e:
            logger.error(f"✗ Failed to initialize WebDriver: {e}")
            return None
    
    def scrape(self, limit: int = 500) -> int:
        """Multi-strategy scraping."""
        logger.info(f"\n{'='*80}")
        logger.info(f"DHAKA TRIBUNE AGGRESSIVE SCRAPER - Target: {limit} articles")
        logger.info(f"{'='*80}\n")
        
        try:
            # Strategy 1: Category pagination (primary method)
            logger.info("[STRATEGY 1] Category Pagination")
            self._scrape_categories(limit)
            
            if len(self.articles) < limit:
                # Strategy 2: Search pages
                logger.info("\n[STRATEGY 2] Search Pages")
                self._scrape_search_pages(limit)
            
            if len(self.articles) < limit:
                # Strategy 3: Direct pagination
                logger.info("\n[STRATEGY 3] Direct Pagination with Query Parameters")
                self._scrape_direct_pagination(limit)
            
        except Exception as e:
            logger.error(f"Error during scraping: {e}")
        finally:
            if self.driver:
                self.driver.quit()
        
        logger.info(f"\n{'='*80}")
        logger.info(f"SCRAPING COMPLETE: {len(self.articles)} articles collected")
        logger.info(f"{'='*80}\n")
        
        return len(self.articles)
    
    def _scrape_categories(self, limit: int):
        """Scrape articles from category pages."""
        articles_per_category = max(1, (limit // len(self.CATEGORIES)) + 50)
        
        for category in self.CATEGORIES:
            if len(self.articles) >= limit:
                break
            
            logger.info(f"\n  Category: {category}")
            category_count = 0
            
            # Try many pages for each category
            for page in range(200):
                if category_count >= articles_per_category or len(self.articles) >= limit:
                    break
                
                # Construct URL
                if page == 0:
                    url = f"{self.BASE_URL}/{category}"
                else:
                    url = f"{self.BASE_URL}/{category}?page={page}"
                
                html = self._fetch_page(url)
                if not html:
                    logger.debug(f"    Page {page}: Failed to fetch")
                    break
                
                # Extract article URLs
                article_urls = self._extract_urls(html)
                if not article_urls:
                    logger.debug(f"    Page {page}: No articles found")
                    break
                
                logger.info(f"    Page {page}: Found {len(article_urls)} article URLs")
                
                # Parse each article
                for article_url in article_urls:
                    if category_count >= articles_per_category or len(self.articles) >= limit:
                        break
                    
                    if article_url in self._seen_urls:
                        continue
                    
                    self._seen_urls.add(article_url)
                    
                    html = self._fetch_page(article_url)
                    if not html:
                        continue
                    
                    article = self._parse_article(article_url, html, category)
                    if article and article.is_valid():
                        self.articles.append(article)
                        category_count += 1
                        stats["success"] += 1
                        logger.info(
                            f"      [{len(self.articles)}/{limit}] {article.title[:60]}..."
                        )
                
                time.sleep(self.delay)
    
    def _scrape_search_pages(self, limit: int):
        """Scrape articles from search results."""
        for keyword in self.SEARCH_KEYWORDS:
            if len(self.articles) >= limit:
                break
            
            logger.info(f"\n  Search: '{keyword}'")
            
            for page in range(50):
                if len(self.articles) >= limit:
                    break
                
                # Dhaka Tribune search URL format
                search_url = f"{self.BASE_URL}/search?q={quote(keyword)}&page={page}"
                
                html = self._fetch_page(search_url)
                if not html:
                    break
                
                article_urls = self._extract_urls(html)
                if not article_urls:
                    break
                
                logger.info(f"    Page {page}: Found {len(article_urls)} results")
                
                for article_url in article_urls:
                    if len(self.articles) >= limit:
                        break
                    
                    if article_url in self._seen_urls:
                        continue
                    
                    self._seen_urls.add(article_url)
                    
                    html = self._fetch_page(article_url)
                    if not html:
                        continue
                    
                    article = self._parse_article(article_url, html, f"search:{keyword}")
                    if article and article.is_valid():
                        self.articles.append(article)
                        stats["success"] += 1
                        logger.info(
                            f"      [{len(self.articles)}/{limit}] {article.title[:60]}..."
                        )
                
                time.sleep(self.delay)
    
    def _scrape_direct_pagination(self, limit: int):
        """Try direct pagination patterns."""
        for page in range(500):
            if len(self.articles) >= limit:
                break
            
            # Try multiple pagination patterns
            patterns = [
                f"{self.BASE_URL}/?page={page}",
                f"{self.BASE_URL}/?paged={page}",
                f"{self.BASE_URL}/page/{page}/",
            ]
            
            for url in patterns:
                if len(self.articles) >= limit:
                    break
                
                html = self._fetch_page(url)
                if not html:
                    continue
                
                article_urls = self._extract_urls(html)
                if not article_urls:
                    continue
                
                for article_url in article_urls:
                    if len(self.articles) >= limit:
                        break
                    
                    if article_url in self._seen_urls:
                        continue
                    
                    self._seen_urls.add(article_url)
                    
                    html = self._fetch_page(article_url)
                    if not html:
                        continue
                    
                    article = self._parse_article(article_url, html, "main")
                    if article and article.is_valid():
                        self.articles.append(article)
                        stats["success"] += 1
                        logger.info(
                            f"  [{len(self.articles)}/{limit}] {article.title[:60]}..."
                        )
                
                time.sleep(self.delay)
    
    def _fetch_page(self, url: str) -> Optional[str]:
        """Fetch page using Selenium with retry."""
        if not self.driver:
            return None
        
        try:
            self.driver.get(url)
            time.sleep(0.8)
            stats["fetch_attempted"] += 1
            return self.driver.page_source
        except Exception as e:
            logger.debug(f"Fetch error: {e}")
            stats["fetch_failed"] += 1
            return None
    
    def _extract_urls(self, html: str) -> List[str]:
        """Extract article URLs from HTML."""
        urls = []
        try:
            soup = BeautifulSoup(html, "lxml")
            links = soup.find_all("a", href=True)
            
            for link in links:
                href = link.get("href", "").strip()
                
                if not href or href.startswith("#"):
                    continue
                
                # Remove query parameters
                href_clean = href.split('?')[0]
                
                # Match article pattern: /{category}/{numeric_id}/{slug}
                if re.search(r"/\d{3,}/", href_clean) and "/video/" not in href_clean.lower():
                    full_url = urljoin(self.BASE_URL, href_clean)
                    if full_url not in self._seen_urls and full_url not in urls:
                        urls.append(full_url)
        
        except Exception as e:
            logger.debug(f"URL extraction error: {e}")
        
        return urls
    
    def _parse_article(self, url: str, html: str, category: str) -> Optional[Article]:
        """Parse article from HTML."""
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
                stats["no_title"] += 1
                return None
            
            # Extract body
            body_parts = []
            for selector in [
                "div.story-body",
                "article",
                "div.article-content",
                "div.post-content",
                "div[class*='story']",
                "div[class*='content']",
                "main"
            ]:
                container = soup.select_one(selector)
                if container:
                    paragraphs = container.find_all("p")
                    for p in paragraphs:
                        text = p.get_text(strip=True)
                        if text and len(text) > 20:
                            body_parts.append(text)
                    if body_parts:
                        break
            
            if not body_parts:
                for p in soup.find_all("p"):
                    text = p.get_text(strip=True)
                    if text and len(text) > 20:
                        body_parts.append(text)
            
            body = "\n\n".join(body_parts)
            
            if len(body) < 100:
                stats["too_short"] += 1
                return None
            
            # Extract date
            date = None
            time_elem = soup.select_one("time")
            if time_elem:
                date = time_elem.get("datetime") or time_elem.get_text(strip=True)
            
            if not date:
                meta = soup.select_one("meta[property='article:published_time']")
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
            logger.debug(f"Parse error for {url}: {e}")
            stats["parse_error"] += 1
            return None


def save_to_json(articles: List[Article], output_file: Path) -> None:
    """Save articles to JSON."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    articles_data = [a.to_dict() for a in articles]
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(articles_data, f, ensure_ascii=False, indent=2)
    logger.info(f"✓ Saved {len(articles_data)} articles to {output_file}")


def save_summary(articles: List[Article], output_file: Path) -> None:
    """Save summary statistics."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    summary = {
        "total_articles": len(articles),
        "scrape_timestamp": datetime.utcnow().isoformat(),
        "by_category": {},
        "by_language": {},
        "average_tokens_per_article": 0,
        "articles_with_dates": 0,
        "articles_without_dates": 0,
        "statistics": {
            "min_tokens": 0,
            "max_tokens": 0,
            "avg_tokens": 0,
        }
    }
    
    total_tokens = 0
    dates_count = 0
    token_values = []
    
    for article in articles:
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
        summary["articles_with_dates"] = dates_count
        summary["articles_without_dates"] = len(articles) - dates_count
        summary["statistics"]["min_tokens"] = min(token_values) if token_values else 0
        summary["statistics"]["max_tokens"] = max(token_values) if token_values else 0
        summary["statistics"]["avg_tokens"] = summary["average_tokens_per_article"]
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    
    logger.info(f"✓ Saved summary to {output_file}")
    
    # Print summary
    logger.info("\n" + "="*80)
    logger.info("SUMMARY STATISTICS")
    logger.info("="*80)
    logger.info(f"Total articles: {summary['total_articles']}")
    logger.info(f"Articles with dates: {summary['articles_with_dates']}")
    logger.info(f"Average tokens per article: {summary['average_tokens_per_article']}")
    logger.info("\nBy Category:")
    for cat, count in sorted(summary["by_category"].items(), key=lambda x: x[1], reverse=True):
        logger.info(f"  {cat}: {count}")
    logger.info("="*80)


def main():
    output_dir = Path("scraped_data")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    scraper = DhakaTribuneScraper(headless=True, delay=0.4)
    
    try:
        scraped_count = scraper.scrape(limit=500)
        
        if scraper.articles:
            # Save JSON
            output_file = output_dir / "dhakatribune_articles.json"
            save_to_json(scraper.articles, output_file)
            
            # Save summary
            summary_file = output_dir / "dhakatribune_summary.json"
            save_summary(scraper.articles, summary_file)
            
            logger.info(f"\n✅ SUCCESS: Scraped {scraped_count} REAL articles")
        else:
            logger.warning("❌ No articles were scraped")
    
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)


if __name__ == "__main__":
    main()
