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
TARGET_DOCS = 1000
MIN_TOKENS = 40
DELAY = 1.0
OUTPUT_FILE = "bn_prothomalo_aggressive.jsonl"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# Multiple strategies to find articles
STRATEGIES = {
    "sitemap": "https://www.prothomalo.com/sitemap.xml",
    "categories": [
        "https://www.prothomalo.com/bangladesh",
        "https://www.prothomalo.com/world",
        "https://www.prothomalo.com/sports",
        "https://www.prothomalo.com/entertainment",
        "https://www.prothomalo.com/business",
        "https://www.prothomalo.com/opinion",
        "https://www.prothomalo.com/lifestyle",
        "https://www.prothomalo.com/education",
        "https://www.prothomalo.com/technology",
    ]
}

stats = Counter()

# ---------------- HELPERS ----------------
def clean(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()

def is_bangla(text, threshold=0.10):
    if not text or len(text) < 10:
        return False
    bangla_chars = sum(1 for c in text if '\u0980' <= c <= '\u09FF')
    return (bangla_chars / len(text)) > threshold

def extract_article(url):
    """Extract article from any Prothom Alo URL"""
    try:
        stats["attempted"] += 1
        
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            stats["http_error"] += 1
            return None

        soup = BeautifulSoup(r.text, "html.parser")

        # Title extraction (multiple fallbacks)
        title = None
        title_selectors = [
            ("h1", None),
            ("meta", {"property": "og:title"}),
            ("meta", {"name": "twitter:title"}),
            (".headline", None),
            (".title", None)
        ]
        
        for tag, attrs in title_selectors:
            if tag == "meta":
                elem = soup.find("meta", attrs)
                if elem and elem.get("content"):
                    title = elem["content"]
                    break
            else:
                elem = soup.find(tag) if attrs is None else soup.find(tag, attrs)
                if elem:
                    title = elem.get_text()
                    break
        
        if not title or len(clean(title)) < 5:
            stats["no_title"] += 1
            return None

        # Body extraction (aggressive approach)
        body_text = ""
        
        # Try structured content first
        article_body = soup.find("article") or soup.find("div", class_=re.compile("story|content|article", re.I))
        
        if article_body:
            # Get all paragraphs
            paragraphs = article_body.find_all("p")
            body_text = " ".join(p.get_text() for p in paragraphs if len(p.get_text().strip()) > 20)
        
        # Fallback: get all paragraphs
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

        if not is_bangla(body_text, threshold=0.10):
            stats["not_bangla"] += 1
            return None

        # Date extraction
        date = None
        time_elem = soup.find("time")
        if time_elem:
            date = time_elem.get("datetime") or time_elem.get_text()
        
        if not date:
            date_meta = soup.find("meta", property="article:published_time")
            if date_meta:
                date = date_meta.get("content")

        stats["success"] += 1
        
        return {
            "title": clean(title),
            "body": body_text,
            "url": url,
            "date": date,
            "language": "bn",
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
        r = requests.get(sitemap_url, timeout=15)
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
        
        # Handle regular sitemap entries
        for url in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}url"):
            loc = url.find("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
            if loc is not None and loc.text:
                # Only include article URLs (not category pages)
                if "/archive/" not in loc.text and any(cat in loc.text for cat in ["bangladesh", "world", "sports", "entertainment", "business", "opinion"]):
                    urls.add(loc.text)
        
        print(f"  ✓ Found {len(urls)} URLs from sitemap")
        
    except Exception as e:
        print(f"  ✗ Sitemap error: {e}")
    
    return urls

def get_urls_from_category(category_url, max_pages=20):
    """Crawl category pages to find article links"""
    urls = set()
    
    try:
        for page in range(1, max_pages + 1):
            page_url = f"{category_url}?page={page}"
            r = requests.get(page_url, headers=HEADERS, timeout=10)
            
            if r.status_code != 200:
                break
            
            soup = BeautifulSoup(r.text, "html.parser")
            
            # Find all links
            links = soup.find_all("a", href=re.compile(r"^https://www\.prothomalo\.com/[^/]+/[^/]+$"))
            
            page_urls = {link["href"] for link in links if link.get("href")}
            
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
    print("AGGRESSIVE PROTHOM ALO SCRAPER")
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
    print(f"  ✗ Not Bangla:      {stats['not_bangla']}")
    print(f"  ✗ HTTP errors:     {stats['http_error']}")
    print(f"  ✗ Other errors:    {stats['error']}")
    print(f"\nSuccess rate: {stats['success']/max(stats['attempted'], 1)*100:.1f}%")
    print(f"Output file: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()