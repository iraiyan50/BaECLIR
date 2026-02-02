"""
Real scraper for Kaler Kantho and Bangla Tribune using Selenium.
Scrapes actual articles from the websites (no dummy data).

Usage:
    python real_scraper.py --source both --output-dir ./scraped_data
"""

import argparse
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
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
    
    def __init__(self, headless: bool = True, delay: float = 2.0):
        self.headless = headless
        self.delay = delay
        self.last_request_time = 0.0
        self.driver = self._init_driver()
    
    def _init_driver(self):
        """Initialize Chrome WebDriver."""
        try:
            chrome_options = Options()
            if self.headless:
                chrome_options.add_argument("--headless")
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
            logger.info("Selenium WebDriver initialized successfully")
            return driver
        except Exception as e:
            logger.error(f"Failed to initialize WebDriver: {e}")
            return None
    
    def _rate_limit(self):
        """Enforce rate limiting."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
    
    def get(self, url: str) -> Optional[str]:
        """Fetch URL using browser."""
        if not self.driver:
            return None
        
        self._rate_limit()
        
        try:
            logger.debug(f"Fetching: {url}")
            self.driver.get(url)
            time.sleep(1)  # Wait for JS rendering
            self.last_request_time = time.time()
            return self.driver.page_source
        except Exception as e:
            logger.warning(f"Error fetching {url}: {e}")
            self.last_request_time = time.time()
            return None
    
    def close(self):
        """Close browser."""
        if self.driver:
            self.driver.quit()


class KalerKanthoScraper:
    """Scraper for Kaler Kantho using Selenium."""
    
    SOURCE_NAME = "kaler_kantho"
    LANGUAGE = "bn"
    BASE_URL = "https://www.kalerkantho.com"
    
    CATEGORIES = [
        "/online/national",
        "/online/politics",
        "/online/world",
        "/online/business",
        "/online/sports",
        "/online/entertainment",
    ]
    
    def __init__(self, browser: Optional[SeleniumBrowserClient] = None):
        self.browser = browser or SeleniumBrowserClient()
        self.articles: List[Article] = []
        self._seen_urls: set = set()
    
    def scrape(self, limit: int = 500) -> int:
        """Scrape articles from Kaler Kantho."""
        logger.info(f"[{self.SOURCE_NAME}] Starting scrape (target: {limit} articles)")
        
        articles_per_category = max(1, (limit // len(self.CATEGORIES)) + 5)
        
        for category in self.CATEGORIES:
            if len(self.articles) >= limit:
                break
            
            logger.info(f"[{self.SOURCE_NAME}] Scraping category: {category}")
            category_count = 0
            
            # Try multiple pages
            for page in range(10):
                if category_count >= articles_per_category or len(self.articles) >= limit:
                    break
                
                if page == 0:
                    url = f"{self.BASE_URL}{category}"
                else:
                    url = f"{self.BASE_URL}{category}?page={page}"
                
                html = self.browser.get(url)
                if not html:
                    break
                
                # Extract article links
                soup = BeautifulSoup(html, "lxml")
                links = soup.find_all("a", href=True)
                
                article_urls = []
                for link in links:
                    href = link.get("href", "")
                    if self._is_article_url(href):
                        full_url = urljoin(self.BASE_URL, href)
                        if full_url not in self._seen_urls:
                            self._seen_urls.add(full_url)
                            article_urls.append(full_url)
                
                logger.info(f"[{self.SOURCE_NAME}] Found {len(article_urls)} article URLs")
                
                # Scrape each article
                for article_url in article_urls:
                    if category_count >= articles_per_category or len(self.articles) >= limit:
                        break
                    
                    html = self.browser.get(article_url)
                    if not html:
                        continue
                    
                    article = self._parse_article(article_url, html)
                    if article:
                        self.articles.append(article)
                        category_count += 1
                        logger.info(f"[{self.SOURCE_NAME}] [{len(self.articles)}/{limit}] {article.title[:60]}...")
                
                if not article_urls:
                    break
        
        logger.info(f"[{self.SOURCE_NAME}] Complete. Total: {len(self.articles)} articles")
        return len(self.articles)
    
    def _is_article_url(self, url: str) -> bool:
        """Check if URL is an article."""
        skip = ["/video/", "/photo/", "/author/", "/topic/", "/tag/", "/category/", "/page/"]
        for s in skip:
            if s in url.lower():
                return False
        return "/online/" in url or re.search(r'/\d{5,}', url)
    
    def _parse_article(self, url: str, html: str) -> Optional[Article]:
        """Parse article from HTML."""
        try:
            soup = BeautifulSoup(html, "lxml")
            
            title = soup.select_one("h1")
            if not title:
                title = soup.select_one("meta[property='og:title']")
                title = title.get("content", "") if title else None
            else:
                title = title.get_text(strip=True)
            
            if not title:
                return None
            
            # Extract body
            body_parts = []
            for selector in ["article", "div.story-details", "div.article-body", "div.content"]:
                container = soup.select_one(selector)
                if container:
                    for p in container.find_all("p"):
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
                return None
            
            # Extract date
            date = None
            time_elem = soup.select_one("time")
            if time_elem:
                date = time_elem.get("datetime") or time_elem.get_text(strip=True)
            
            category = url.split("/")[-3] if "/" in url else "general"
            
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


class BanglaTribuneScraper:
    """Scraper for Bangla Tribune using Selenium."""
    
    SOURCE_NAME = "bangla_tribune"
    LANGUAGE = "bn"
    BASE_URL = "https://www.banglatribune.com"
    
    CATEGORIES = [
        "/national",
        "/country",
        "/politics",
        "/foreign",
        "/business",
        "/sport",
        "/entertainment",
    ]
    
    def __init__(self, browser: Optional[SeleniumBrowserClient] = None):
        self.browser = browser or SeleniumBrowserClient()
        self.articles: List[Article] = []
        self._seen_urls: set = set()
    
    def scrape(self, limit: int = 500) -> int:
        """Scrape articles from Bangla Tribune."""
        logger.info(f"[{self.SOURCE_NAME}] Starting scrape (target: {limit} articles)")
        
        articles_per_category = max(1, (limit // len(self.CATEGORIES)) + 5)
        
        for category in self.CATEGORIES:
            if len(self.articles) >= limit:
                break
            
            logger.info(f"[{self.SOURCE_NAME}] Scraping category: {category}")
            category_count = 0
            
            # Try multiple pages
            for page in range(15):
                if category_count >= articles_per_category or len(self.articles) >= limit:
                    break
                
                if page == 0:
                    url = f"{self.BASE_URL}{category}"
                else:
                    url = f"{self.BASE_URL}{category}?page={page}"
                
                html = self.browser.get(url)
                if not html:
                    break
                
                # Extract article links
                soup = BeautifulSoup(html, "lxml")
                links = soup.find_all("a", href=True)
                
                article_urls = []
                for link in links:
                    href = link.get("href", "")
                    if re.search(r"/\d{6}/", href):  # Bangla Tribune pattern
                        full_url = urljoin(self.BASE_URL, href)
                        if full_url not in self._seen_urls:
                            self._seen_urls.add(full_url)
                            article_urls.append(full_url)
                
                logger.info(f"[{self.SOURCE_NAME}] Found {len(article_urls)} article URLs")
                
                # Scrape each article
                for article_url in article_urls:
                    if category_count >= articles_per_category or len(self.articles) >= limit:
                        break
                    
                    html = self.browser.get(article_url)
                    if not html:
                        continue
                    
                    article = self._parse_article(article_url, html)
                    if article:
                        self.articles.append(article)
                        category_count += 1
                        logger.info(f"[{self.SOURCE_NAME}] [{len(self.articles)}/{limit}] {article.title[:60]}...")
                
                if not article_urls:
                    break
        
        logger.info(f"[{self.SOURCE_NAME}] Complete. Total: {len(self.articles)} articles")
        return len(self.articles)
    
    def _parse_article(self, url: str, html: str) -> Optional[Article]:
        """Parse article from HTML."""
        try:
            soup = BeautifulSoup(html, "lxml")
            
            title = soup.select_one("h1")
            if not title:
                title = soup.select_one("meta[property='og:title']")
                title = title.get("content", "") if title else None
            else:
                title = title.get_text(strip=True)
            
            if not title:
                return None
            
            # Extract body
            body_parts = []
            for selector in ["article", "div.news-details", "div.content", "div.article-content"]:
                container = soup.select_one(selector)
                if container:
                    for p in container.find_all("p"):
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
                return None
            
            # Extract date from span with class="tts_time" and content attribute
            date = None
            # Try span with tts_time class first
            tts_span = soup.select_one("span.tts_time")
            if tts_span:
                date = tts_span.get("content")
            
            # Fallback to time element
            if not date:
                time_elem = soup.select_one("time")
                if time_elem:
                    date = time_elem.get("datetime") or time_elem.get_text(strip=True)
            
            category = url.split("/")[3] if len(url.split("/")) > 3 else "general"
            
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
    """Save summary."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    summary = {
        "total_articles": len(articles),
        "scrape_timestamp": datetime.utcnow().isoformat(),
        "by_source": {},
        "by_category": {},
        "by_language": {},
        "average_tokens_per_article": 0,
    }
    
    total_tokens = 0
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
    
    if articles:
        summary["average_tokens_per_article"] = round(total_tokens / len(articles), 2)
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Saved summary to {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Scrape real articles from Kaler Kantho and Bangla Tribune"
    )
    parser.add_argument(
        "--source",
        choices=["kaler_kantho", "bangla_tribune", "both"],
        default="both",
    )
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--output-dir", type=Path, default=Path("scraped_data"))
    
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    
    all_articles = []
    browser = SeleniumBrowserClient(headless=True, delay=1.5)
    
    try:
        if args.source in ["kaler_kantho", "both"]:
            logger.info("="*80)
            logger.info("Starting Kaler Kantho scraper")
            logger.info("="*80)
            
            scraper = KalerKanthoScraper(browser=browser)
            scraper.scrape(limit=args.limit)
            
            if scraper.articles:
                output_file = args.output_dir / "kaler_kantho_articles.json"
                save_to_json(scraper.articles, output_file)
                all_articles.extend(scraper.articles)
            
            logger.info(f"Kaler Kantho: {len(scraper.articles)} articles scraped\n")
        
        if args.source in ["bangla_tribune", "both"]:
            logger.info("="*80)
            logger.info("Starting Bangla Tribune scraper")
            logger.info("="*80)
            
            scraper = BanglaTribuneScraper(browser=browser)
            scraper.scrape(limit=args.limit)
            
            if scraper.articles:
                output_file = args.output_dir / "bangla_tribune_articles.json"
                save_to_json(scraper.articles, output_file)
                all_articles.extend(scraper.articles)
            
            logger.info(f"Bangla Tribune: {len(scraper.articles)} articles scraped\n")
        
        if all_articles:
            summary_file = args.output_dir / "summary.json"
            save_summary(all_articles, summary_file)
            
            logger.info("="*80)
            logger.info("SCRAPING COMPLETE")
            logger.info("="*80)
            logger.info(f"Total articles scraped: {len(all_articles)}")
            logger.info(f"Output directory: {args.output_dir.absolute()}")
    
    finally:
        browser.close()


if __name__ == "__main__":
    main()
