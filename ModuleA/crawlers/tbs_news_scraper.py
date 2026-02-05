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
OUTPUT_FILE = "tbs_news_articles.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Multiple strategies to find articles
STRATEGIES = {
    "sitemap": "https://www.tbsnews.net/sitemap.xml",
    "categories": [
        "https://www.tbsnews.net/bangladesh",
        "https://www.tbsnews.net/world",
        "https://www.tbsnews.net/economy",
        "https://www.tbsnews.net/sports",
        "https://www.tbsnews.net/entertainment",
        "https://www.tbsnews.net/opinion",
        "https://www.tbsnews.net/feature",
        "https://www.tbsnews.net/tech",
        "https://www.tbsnews.net/climate-change",
        "https://www.tbsnews.net/youth",
    ]
}

stats = Counter()

# ---------------- HELPERS ----------------
def clean(text):
    """Clean whitespace from text"""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()

def extract_article(url):
    """Extract article content from TBS News URL"""
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
            soup.find("h1", class_=re.compile("title|headline|post-title|news-title|article-title", re.I)),
            soup.find("h1"),
            soup.find("meta", property="og:title"),
            soup.find("meta", {"name": "twitter:title"}),
            soup.find("div", class_=re.compile("headline|news-headline", re.I)),
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
        
        # Try to find article body with common selectors for TBS News
        article_selectors = [
            soup.find("div", class_=re.compile("article-body|story-content|post-content|news-content|detail-content|entry-content|field-name-body|story_details", re.I)),
            soup.find("article"),
            soup.find("div", {"itemprop": "articleBody"}),
            soup.find("div", class_=re.compile("content-details|news-details|article-details|body-content", re.I)),
            soup.find("div", id=re.compile("article|content|news|body", re.I)),
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
            date_elem = soup.find(class_=re.compile("date|time|published|publish|update|timestamp", re.I))
            if date_elem:
                date = clean(date_elem.get_text())
        
        # Extract author if available
        author = None
        author_elem = soup.find("meta", {"name": "author"})
        if author_elem:
            author = author_elem.get("content")
        
        if not author:
            author_elem = soup.find(class_=re.compile("author|writer|reporter|byline|contributor", re.I))
            if author_elem:
                author = clean(author_elem.get_text())
        
        if not author:
            author_elem = soup.find("a", rel="author")
            if author_elem:
                author = clean(author_elem.get_text())
        
        # Extract category from URL
        category = None
        if "/bangladesh/" in url:
            category = "bangladesh"
        elif "/world/" in url:
            category = "world"
        elif "/economy/" in url:
            category = "economy"
        elif "/sports/" in url:
            category = "sports"
        elif "/entertainment/" in url:
            category = "entertainment"
        elif "/opinion/" in url:
            category = "opinion"
        elif "/feature/" in url:
            category = "feature"
        elif "/tech/" in url:
            category = "tech"
        elif "/climate-change/" in url:
            category = "climate-change"
        elif "/youth/" in url:
            category = "youth"

        stats["success"] += 1
        
        return {
            "title": clean(title),
            "body": body_text,
            "url": url,
            "date": date,
            "author": author,
            "category": category,
            "language": "en",
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
        # Try with different headers to avoid 403
        headers_variants = [
            HEADERS,
            {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/xml,text/xml,*/*",
            },
            {
                "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
            }
        ]
        
        r = None
        for headers in headers_variants:
            try:
                r = requests.get(sitemap_url, headers=headers, timeout=15)
                if r.status_code == 200:
                    break
            except:
                continue
        
        if not r or r.status_code != 200:
            print(f"  ✗ Sitemap blocked (HTTP {r.status_code if r else 'N/A'})")
            print(f"  → Will rely on category crawling instead")
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
                    if any(cat in url_text for cat in ["bangladesh", "world", "economy", "sports", "entertainment", "opinion", "feature", "tech", "climate-change", "youth"]):
                        urls.add(url_text)
                        if len(urls) >= max_urls:
                            break
        
        print(f"  ✓ Found {len(urls)} URLs from sitemap")
        
    except Exception as e:
        print(f"  ✗ Sitemap error: {e}")
        print(f"  → Will rely on category crawling instead")
    
    return urls

def get_urls_from_category(category_url, max_pages=50):
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
                    # Try with trailing slash
                    page_url = f"{category_url}/?page={page}"
                    r = requests.get(page_url, headers=HEADERS, timeout=10)
                    if r.status_code != 200:
                        break
            
            soup = BeautifulSoup(r.text, "html.parser")
            
            # Find all article links - be more aggressive
            all_links = soup.find_all("a", href=True)
            
            page_urls = set()
            for link in all_links:
                href = link.get("href")
                
                # Make sure it's a tbsnews.net URL
                if not href:
                    continue
                    
                # Convert relative URLs to absolute
                if href.startswith("/"):
                    href = f"https://www.tbsnews.net{href}"
                
                if not href.startswith("https://www.tbsnews.net/"):
                    continue
                
                # Exclude non-article pages
                if any(exclude in href for exclude in ["/page/", "/tag/", "/author/", "/category/", "/archive/", "#"]):
                    continue
                
                # Check if it's likely an article URL
                if any(cat in href for cat in ["bangladesh", "world", "economy", "sports", "entertainment", "opinion", "feature", "tech", "climate-change", "youth"]):
                    # Make sure it has content after the category
                    if href.rstrip("/").count("/") >= 4:  # domain/category/article-slug
                        page_urls.add(href)
            
            if not page_urls:
                # If no new URLs found, try a few more pages before giving up
                if page < 5:
                    continue
                else:
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
        print(f"  [{i}/{len(STRATEGIES['categories'])}] {category.split('/')[-1]}...", end=" ")
        urls = get_urls_from_category(category, max_pages=50)
        all_urls.update(urls)
        print(f"→ {len(urls)} URLs")
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
    print("TBS NEWS ARTICLE SCRAPER")
    print("="*70)
    print(f"Target: {TARGET_DOCS} articles")
    print(f"Output: {OUTPUT_FILE}")
    
    all_urls = set()
    
    # Strategy 1: Sitemap (may fail with 403)
    sitemap_urls = get_urls_from_sitemap(STRATEGIES["sitemap"])
    all_urls.update(sitemap_urls)
    
    # Strategy 2: Category pages (always run for maximum coverage)
    print(f"\n  💡 Sitemap found {len(sitemap_urls)} URLs")
    print(f"  💡 Running category crawling for maximum coverage...")
    
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
