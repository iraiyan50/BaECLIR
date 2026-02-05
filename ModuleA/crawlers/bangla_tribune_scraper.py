import requests
import time
import json
import re
from bs4 import BeautifulSoup
from datetime import datetime
from collections import Counter
import xml.etree.ElementTree as ET

# ---------------- CONFIG ----------------
TARGET_DOCS = 500
MIN_TOKENS = 40
DELAY = 1.0
OUTPUT_FILE = "bangla_tribune_articles.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Multiple strategies to find articles
STRATEGIES = {
    "sitemap": "https://www.banglatribune.com/sitemap.xml",
    "categories": [
        "https://www.banglatribune.com/country",
        "https://www.banglatribune.com/international",
        "https://www.banglatribune.com/sports",
        "https://www.banglatribune.com/entertainment",
        "https://www.banglatribune.com/business",
        "https://www.banglatribune.com/youth",
        "https://www.banglatribune.com/lifestyle",
        "https://www.banglatribune.com/technology",
        "https://www.banglatribune.com/education",
        "https://www.banglatribune.com/health",
    ]
}

stats = Counter()

# ---------------- HELPERS ----------------
def clean(text):
    """Clean whitespace from text"""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()

def is_bangla(text, threshold=0.10):
    """Check if text contains Bangla characters"""
    if not text or len(text) < 10:
        return False
    bangla_chars = sum(1 for c in text if '\u0980' <= c <= '\u09FF')
    return (bangla_chars / len(text)) > threshold

def extract_article(url):
    """Extract article content from Bangla Tribune URL"""
    try:
        stats["attempted"] += 1
        
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            stats["http_error"] += 1
            return None

        soup = BeautifulSoup(r.text, "html.parser")

        # Title extraction (multiple fallbacks)
        title = None
        
        # Try different title selectors
        title_selectors = [
            soup.find("h1", class_=re.compile("title|headline", re.I)),
            soup.find("h1"),
            soup.find("meta", property="og:title"),
            soup.find("meta", {"name": "twitter:title"}),
            soup.find("div", class_=re.compile("title", re.I)),
        ]
        
        for elem in title_selectors:
            if elem:
                if elem.name == "meta":
                    title = elem.get("content")
                else:
                    title = elem.get_text()
                if title and len(clean(title)) > 5:
                    break
        
        if not title or len(clean(title)) < 5:
            stats["no_title"] += 1
            return None

        # Body extraction
        body_text = ""
        
        # Try to find article body with common selectors for Bangla sites
        article_selectors = [
            soup.find("div", class_=re.compile("article-body|story-content|post-content|news-content|detail-content", re.I)),
            soup.find("article"),
            soup.find("div", {"itemprop": "articleBody"}),
            soup.find("div", class_=re.compile("content-details|news-details", re.I)),
        ]
        
        article_body = None
        for selector in article_selectors:
            if selector:
                article_body = selector
                break
        
        if article_body:
            # Get all paragraphs from article body
            paragraphs = article_body.find_all("p")
            body_text = " ".join(p.get_text() for p in paragraphs if len(p.get_text().strip()) > 15)
        
        # Fallback: get all paragraphs from page
        if not body_text or len(body_text.split()) < 30:
            all_paragraphs = soup.find_all("p")
            body_text = " ".join(p.get_text() for p in all_paragraphs if len(p.get_text().strip()) > 15)
        
        if not body_text:
            stats["no_body"] += 1
            return None

        body_text = clean(body_text)
        tokens = body_text.split()
        
        if len(tokens) < MIN_TOKENS:
            stats["too_short"] += 1
            return None

        # Check if it's Bangla content
        if not is_bangla(body_text, threshold=0.10):
            stats["not_bangla"] += 1
            return None

        # Date extraction
        date = None
        
        # Try multiple date selectors
        time_elem = soup.find("time")
        if time_elem:
            date = time_elem.get("datetime") or time_elem.get_text()
        
        if not date:
            date_meta = soup.find("meta", property="article:published_time")
            if date_meta:
                date = date_meta.get("content")
        
        if not date:
            # Try to find date in common class names
            date_elem = soup.find(class_=re.compile("date|time|published", re.I))
            if date_elem:
                date = date_elem.get_text()
        
        # Extract author if available
        author = None
        author_elem = soup.find("meta", {"name": "author"})
        if author_elem:
            author = author_elem.get("content")
        
        if not author:
            author_elem = soup.find(class_=re.compile("author", re.I))
            if author_elem:
                author = author_elem.get_text().strip()
        
        # Extract category from URL
        category = None
        if "/country/" in url:
            category = "country"
        elif "/international/" in url:
            category = "international"
        elif "/sports/" in url:
            category = "sports"
        elif "/entertainment/" in url:
            category = "entertainment"
        elif "/business/" in url:
            category = "business"
        elif "/youth/" in url:
            category = "youth"
        elif "/lifestyle/" in url:
            category = "lifestyle"
        elif "/technology/" in url:
            category = "technology"
        elif "/education/" in url:
            category = "education"
        elif "/health/" in url:
            category = "health"

        stats["success"] += 1
        
        return {
            "title": clean(title),
            "body": body_text,
            "url": url,
            "date": date,
            "author": author,
            "category": category,
            "language": "bn",
            "token_count": len(tokens),
            "scraped_at": datetime.now().isoformat()
        }

    except Exception as e:
        stats["error"] += 1
        return None

def get_urls_from_sitemap(sitemap_url, max_urls=2000):
    """Extract article URLs from sitemap"""
    print("\n[1/3] Fetching URLs from sitemap...")
    urls = set()
    
    try:
        r = requests.get(sitemap_url, headers=HEADERS, timeout=15)
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
                if len(urls) < max_urls:
                    print(f"  → Fetching sub-sitemap: {loc.text.split('/')[-1]}")
                    sub_urls = get_urls_from_sitemap(loc.text, max_urls - len(urls))
                    urls.update(sub_urls)
        
        # Handle regular sitemap entries
        for url in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}url"):
            loc = url.find("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
            if loc is not None and loc.text:
                url_text = loc.text
                # Only include article URLs (exclude category/archive pages)
                if all(exclude not in url_text for exclude in ["/page/", "/tag/", "/author/", "/category/", "/archive/"]):
                    if any(cat in url_text for cat in ["country", "international", "sports", "entertainment", "business", "youth", "lifestyle", "technology", "education", "health"]):
                        urls.add(url_text)
                        if len(urls) >= max_urls:
                            break
        
        print(f"  ✓ Found {len(urls)} URLs from sitemap")
        
    except Exception as e:
        print(f"  ✗ Sitemap error: {e}")
    
    return urls

def get_urls_from_category(category_url, max_pages=30):
    """Crawl category pages to find article links"""
    urls = set()
    
    try:
        for page in range(1, max_pages + 1):
            # Try different pagination formats
            page_url = f"{category_url}?page={page}"
            r = requests.get(page_url, headers=HEADERS, timeout=10)
            
            if r.status_code != 200:
                # Try alternative pagination
                page_url = f"{category_url}/page/{page}"
                r = requests.get(page_url, headers=HEADERS, timeout=10)
                if r.status_code != 200:
                    break
            
            soup = BeautifulSoup(r.text, "html.parser")
            
            # Find all article links
            links = soup.find_all("a", href=re.compile(r"^https://www\.banglatribune\.com/"))
            
            page_urls = set()
            for link in links:
                href = link.get("href")
                if href and all(exclude not in href for exclude in ["/page/", "/tag/", "/author/", "/category/", "/archive/"]):
                    # Check if it's likely an article URL
                    if any(cat in href for cat in ["country", "international", "sports", "entertainment", "business", "youth", "lifestyle", "technology", "education", "health"]):
                        # Make sure it has a numeric ID or slug pattern (article URLs)
                        if re.search(r'/\d+$', href) or re.search(r'/[a-z0-9-]+$', href):
                            page_urls.add(href)
            
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
    
    for i, category in enumerate(STRATEGIES["categories"], 1):
        print(f"  [{i}/{len(STRATEGIES['categories'])}] {category.split('/')[-1]}")
        urls = get_urls_from_category(category, max_pages=30)
        all_urls.update(urls)
        print(f"      → Found {len(urls)} URLs")
        time.sleep(1)
    
    print(f"  ✓ Total: {len(all_urls)} unique URLs from categories")
    return all_urls

def scrape_articles(urls):
    """Scrape articles from URL list"""
    print(f"\n[3/3] Scraping articles...")
    docs = []
    
    # Sort URLs to get a diverse set
    url_list = list(urls)
    
    for i, url in enumerate(url_list):
        if len(docs) >= TARGET_DOCS:
            break
        
        # Print progress every 25 articles
        if i % 25 == 0:
            print(f"  Progress: {len(docs)}/{TARGET_DOCS} articles collected ({i} URLs tried)")
        
        article = extract_article(url)
        
        if article:
            docs.append(article)
        
        time.sleep(DELAY)
    
    print(f"  ✓ Final: {len(docs)}/{TARGET_DOCS} articles collected")
    return docs

# ---------------- MAIN ----------------
def main():
    print("="*70)
    print("BANGLA TRIBUNE ARTICLE SCRAPER")
    print("="*70)
    print(f"Target: {TARGET_DOCS} articles")
    print(f"Output: {OUTPUT_FILE}")
    
    all_urls = set()
    
    # Strategy 1: Sitemap
    sitemap_urls = get_urls_from_sitemap(STRATEGIES["sitemap"])
    all_urls.update(sitemap_urls)
    
    # Strategy 2: Category pages (if sitemap didn't get enough)
    if len(all_urls) < TARGET_DOCS * 2:
        category_urls = get_urls_from_categories()
        all_urls.update(category_urls)
    
    print(f"\n{'='*70}")
    print(f"Total unique URLs collected: {len(all_urls)}")
    print(f"{'='*70}")
    
    if len(all_urls) < 100:
        print("\n⚠️  Warning: Very few URLs found. Continuing anyway...")
    
    # Scrape articles
    docs = scrape_articles(all_urls)
    
    # Save to JSON file
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(docs, f, ensure_ascii=False, indent=2)
    
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
    
    # Show sample article
    if docs:
        print(f"\nSample article (first one):")
        print(f"  Title: {docs[0]['title'][:80]}...")
        print(f"  Tokens: {docs[0]['token_count']}")
        print(f"  Category: {docs[0].get('category', 'N/A')}")
        print(f"  Date: {docs[0].get('date', 'N/A')}")
        print(f"  Language: {docs[0]['language']}")

if __name__ == "__main__":
    main()
