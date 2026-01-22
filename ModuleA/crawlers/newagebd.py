import requests
import time
import json
import re
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from tqdm import tqdm
from collections import Counter
import xml.etree.ElementTree as ET

# ---------------- CONFIG ----------------
TARGET_DOCS = 500
MIN_TOKENS = 40
DELAY = 1.0
OUTPUT_FILE = "newagebd_articles.jsonl"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# New Age BD strategies
STRATEGIES = {
    "sitemap": "https://www.newagebd.net/sitemap.xml",
    "categories": [
        "https://www.newagebd.net/",
        "https://www.newagebd.net/category/bangladesh/",
        "https://www.newagebd.net/category/world/",
        "https://www.newagebd.net/category/business/",
        "https://www.newagebd.net/category/sports/",
        "https://www.newagebd.net/category/entertainment/",
        "https://www.newagebd.net/category/lifestyle/",
        "https://www.newagebd.net/category/opinion/",
        "https://www.newagebd.net/category/tech/",
    ]
}

stats = Counter()

# ---------------- HELPERS ----------------
def clean(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()

def is_english(text, threshold=0.70):
    """Check if text is predominantly English"""
    if not text or len(text) < 10:
        return False
    # Count ASCII letters
    ascii_chars = sum(1 for c in text if c.isascii() and c.isalpha())
    total_chars = sum(1 for c in text if c.isalpha())
    if total_chars == 0:
        return False
    return (ascii_chars / total_chars) > threshold

def extract_article(url):
    """Extract article from New Age BD URL"""
    try:
        stats["attempted"] += 1
        
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            stats["http_error"] += 1
            return None

        soup = BeautifulSoup(r.text, "html.parser")

        # Title extraction for New Age BD
        title = None
        title_selectors = [
            ("h1", {"class": re.compile("headline|title|post-title", re.I)}),
            ("h1", None),
            ("meta", {"property": "og:title"}),
            ("meta", {"name": "twitter:title"}),
        ]
        
        for tag, attrs in title_selectors:
            if tag == "meta":
                elem = soup.find("meta", attrs)
                if elem and elem.get("content"):
                    title = elem["content"]
                    break
            else:
                if attrs:
                    elem = soup.find(tag, attrs)
                else:
                    elem = soup.find(tag)
                if elem:
                    title = elem.get_text()
                    break
        
        if not title or len(clean(title)) < 5:
            stats["no_title"] += 1
            return None

        # Body extraction for New Age BD structure
        body_text = ""
        
        # Try different content containers used by New Age BD
        content_selectors = [
            {"class": re.compile("article-body|entry-content|post-content|content-body", re.I)},
            {"class": "article-text"},
            {"itemprop": "articleBody"},
            {"class": "the-content"},
        ]
        
        article_body = None
        for selector in content_selectors:
            article_body = soup.find("div", selector)
            if article_body:
                break
        
        # If no specific container found, try article tag
        if not article_body:
            article_body = soup.find("article")
        
        if article_body:
            # Remove unwanted elements
            for unwanted in article_body.find_all(['script', 'style', 'aside', 'nav', 'footer']):
                unwanted.decompose()
            
            # Get all paragraphs
            paragraphs = article_body.find_all("p")
            body_text = " ".join(p.get_text() for p in paragraphs if len(p.get_text().strip()) > 20)
        
        # Fallback: get all paragraphs from page
        if not body_text or len(body_text.split()) < 30:
            all_p = soup.find_all("p")
            body_text = " ".join(p.get_text() for p in all_p if len(p.get_text().strip()) > 20)
        
        if not body_text:
            stats["no_body"] += 1
            return None

        body_text = clean(body_text)
        tokens = body_text.split()
        
        if len(tokens) < MIN_TOKENS:
            stats["too_short"] += 1
            return None

        if not is_english(body_text, threshold=0.70):
            stats["not_english"] += 1
            return None

        # Date extraction
        date = None
        # Try multiple date selectors
        date_selectors = [
            ("time", {"datetime": True}),
            ("meta", {"property": "article:published_time"}),
            ("meta", {"name": "publish_date"}),
            ("span", {"class": re.compile("date|time|published", re.I)}),
        ]
        
        for tag, attrs in date_selectors:
            if tag == "meta":
                elem = soup.find("meta", attrs)
                if elem and elem.get("content"):
                    date = elem["content"]
                    break
            elif tag == "time":
                elem = soup.find("time")
                if elem:
                    date = elem.get("datetime") or elem.get_text()
                    break
            else:
                elem = soup.find(tag, attrs)
                if elem:
                    date = elem.get_text()
                    break

        stats["success"] += 1
        
        return {
            "title": clean(title),
            "body": body_text,
            "url": url,
            "date": date,
            "language": "en",
            "source": "New Age BD",
            "token_count": len(tokens)
        }

    except Exception as e:
        stats["error"] += 1
        return None

def get_urls_from_sitemap(sitemap_url):
    """Extract article URLs from sitemap"""
    print("\n[1/3] Fetching URLs from sitemap...")
    urls = set()
    
    try:
        r = requests.get(sitemap_url, timeout=15, headers=HEADERS)
        if r.status_code != 200:
            print(f"  ✗ Sitemap failed: HTTP {r.status_code}")
            return urls
        
        # Parse XML sitemap
        root = ET.fromstring(r.content)
        
        # Handle sitemap index (links to other sitemaps)
        for sitemap in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}sitemap"):
            loc = sitemap.find("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
            if loc is not None and loc.text:
                # Recursively get URLs from sub-sitemap
                sub_urls = get_urls_from_sitemap(loc.text)
                urls.update(sub_urls)
                if len(urls) > 5000:  # Limit total URLs
                    break
        
        # Handle regular sitemap entries
        for url in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}url"):
            loc = url.find("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
            if loc is not None and loc.text:
                # Filter for article URLs
                url_text = loc.text
                # Exclude category/archive pages, include actual articles
                if "newagebd.net" in url_text and "/category/" not in url_text:
                    if not any(exclude in url_text for exclude in ["/page/", "/tag/"]):
                        urls.add(url_text)
        
        print(f"  ✓ Found {len(urls)} URLs from sitemap")
        
    except Exception as e:
        print(f"  ✗ Sitemap error: {e}")
    
    return urls

def get_urls_from_category(category_url, max_pages=20):
    """Crawl category pages to find article links"""
    urls = set()
    
    try:
        for page in range(1, max_pages + 1):
            # New Age BD pagination format
            if page == 1:
                page_url = category_url
            else:
                page_url = f"{category_url}page/{page}/"
            
            r = requests.get(page_url, headers=HEADERS, timeout=10)
            
            if r.status_code != 200:
                break
            
            soup = BeautifulSoup(r.text, "html.parser")
            
            # Find article links
            links = soup.find_all("a", href=re.compile(r"^https://www\.newagebd\.net/.*"))
            
            page_urls = set()
            for link in links:
                href = link.get("href")
                if href and "/category/" not in href and "newagebd.net" in href:
                    # Ensure it's an article, not a homepage or category
                    if href.rstrip('/').count('/') >= 4:  # Articles typically have deeper paths
                        page_urls.add(href.rstrip('/'))
            
            if not page_urls:
                break
            
            urls.update(page_urls)
            time.sleep(0.5)
        
    except Exception as e:
        pass
    
    return urls

def get_urls_from_categories():
    """Get URLs from all category pages"""
    print("\n[2/3] Crawling category pages...")
    all_urls = set()
    
    for category in tqdm(STRATEGIES["categories"], desc="Categories"):
        urls = get_urls_from_category(category, max_pages=30)
        all_urls.update(urls)
        time.sleep(1)
    
    print(f"  ✓ Found {len(all_urls)} unique URLs from categories")
    return all_urls

def scrape_articles(urls):
    """Scrape articles from URL list"""
    print(f"\n[3/3] Scraping {len(urls)} articles...")
    docs = []
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for url in tqdm(list(urls)[:TARGET_DOCS * 3], desc="Scraping"):  # Try 3x target
            if len(docs) >= TARGET_DOCS:
                break
            
            article = extract_article(url)
            
            if article:
                f.write(json.dumps(article, ensure_ascii=False) + "\n")
                f.flush()
                docs.append(article)
            
            time.sleep(DELAY)
    
    return docs

# ---------------- MAIN ----------------
def main():
    print("="*70)
    print("NEW AGE BD SCRAPER")
    print("="*70)
    
    all_urls = set()
    
    # Strategy 1: Sitemap
    sitemap_urls = get_urls_from_sitemap(STRATEGIES["sitemap"])
    all_urls.update(sitemap_urls)
    
    # Strategy 2: Category pages
    category_urls = get_urls_from_categories()
    all_urls.update(category_urls)
    
    print(f"\n{'='*70}")
    print(f"Total unique URLs collected: {len(all_urls)}")
    print(f"{'='*70}")
    
    if len(all_urls) < 100:
        print("\n⚠️  Warning: Very few URLs found. Continuing anyway...")
    
    # Scrape articles
    docs = scrape_articles(all_urls)
    
    # Final stats
    print("\n" + "="*70)
    print(f"COLLECTION COMPLETE: {len(docs)} articles saved")
    print("="*70)
    print("\nStatistics:")
    print(f"  URLs attempted:    {stats['attempted']}")
    print(f"  ✓ Success:         {stats['success']}")
    print(f"  ✗ No title:        {stats['no_title']}")
    print(f"  ✗ No body:         {stats['no_body']}")
    print(f"  ✗ Too short:       {stats['too_short']}")
    print(f"  ✗ Not English:     {stats['not_english']}")
    print(f"  ✗ HTTP errors:     {stats['http_error']}")
    print(f"  ✗ Other errors:    {stats['error']}")
    print(f"\nSuccess rate: {stats['success']/max(stats['attempted'], 1)*100:.1f}%")
    print(f"Output file: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
