"""
Cross-Lingual Information Retrieval System
for The Daily Star (thedailystar.net)

This system implements:
- Web scraping with BeautifulSoup
- Inverted index construction
- Multiple retrieval methods (TF-IDF, BM25)
- Multilingual support with embeddings
- Query translation and NE mapping
- Performance evaluation
- Complete JSON data export
"""

import requests
from bs4 import BeautifulSoup
import time
import json
import re
from datetime import datetime
from collections import defaultdict, Counter
import math
from typing import List, Dict, Tuple
import numpy as np

# Optional imports (install if needed)
try:
    from sentence_transformers import SentenceTransformer
    EMBEDDINGS_AVAILABLE = True
except ImportError:
    EMBEDDINGS_AVAILABLE = False
    print("Warning: sentence-transformers not available. Install with: pip install sentence-transformers")

try:
    from googletrans import Translator
    TRANSLATION_AVAILABLE = True
except ImportError:
    TRANSLATION_AVAILABLE = False
    print("Warning: googletrans not available. Install with: pip install googletrans==4.0.0-rc1")


class DailyStarScraper:
    """Scraper for The Daily Star website"""
    
    def __init__(self, base_url="https://www.thedailystar.net", delay=2):
        self.base_url = base_url
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def scrape_article(self, url: str) -> Dict:
        """Scrape a single article"""
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract title
            title = soup.find('h1')
            title = title.get_text(strip=True) if title else "No title"
            
            # Extract body - adjust selectors based on actual site structure
            body_elements = soup.find_all(['p', 'div'], class_=re.compile('article|content|body'))
            body = ' '.join([el.get_text(strip=True) for el in body_elements])
            
            # Extract date
            date_elem = soup.find('time')
            date = date_elem.get('datetime', '') if date_elem else datetime.now().strftime('%Y-%m-%d')
            
            # Count tokens
            tokens = body.split()
            
            return {
                'title': title,
                'body': body,
                'url': url,
                'date': date,
                'language': 'en',
                'tokens': len(tokens),
                'word_embeddings': None,
                'named_entities': self.extract_named_entities(body)
            }
        except Exception as e:
            print(f"Error scraping {url}: {e}")
            return None
    
    def extract_named_entities(self, text: str) -> List[str]:
        """Simple NE extraction using capitalization patterns"""
        # This is a simple heuristic - use spaCy or similar for better results
        words = text.split()
        entities = []
        for i, word in enumerate(words):
            if word and word[0].isupper() and len(word) > 1:
                # Check if it's not sentence start
                if i > 0 or (i == 0 and words[i-1][-1] not in '.!?'):
                    entities.append(word)
        return list(set(entities))[:10]  # Return top 10 unique entities
    
    def scrape_homepage_links(self) -> List[str]:
        """Extract article links from homepage"""
        try:
            response = self.session.get(self.base_url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            
            links = []
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                if '/news/' in href or '/article/' in href:
                    if href.startswith('/'):
                        href = self.base_url + href
                    if href not in links:
                        links.append(href)
            
            return links[:50]  # Limit to 50 articles
        except Exception as e:
            print(f"Error scraping homepage: {e}")
            return []
    
    def scrape_multiple(self, max_pages=50) -> List[Dict]:
        """Scrape multiple articles"""
        print(f"Fetching article links from {self.base_url}...")
        article_urls = self.scrape_homepage_links()
        
        documents = []
        for i, url in enumerate(article_urls[:max_pages], 1):
            print(f"Scraping article {i}/{min(len(article_urls), max_pages)}: {url}")
            doc = self.scrape_article(url)
            if doc:
                documents.append(doc)
            time.sleep(self.delay)
        
        return documents


class InvertedIndex:
    """Inverted index for efficient retrieval"""
    
    def __init__(self):
        self.index = defaultdict(list)  # term -> [(doc_id, tf), ...]
        self.doc_lengths = {}  # doc_id -> length
        self.doc_metadata = {}  # doc_id -> metadata
        self.vocabulary = set()
        self.total_docs = 0
        self.avg_doc_length = 0
    
    def tokenize(self, text: str) -> List[str]:
        """Simple tokenization"""
        text = text.lower()
        text = re.sub(r'[^\w\s]', ' ', text)
        tokens = text.split()
        return [t for t in tokens if len(t) > 2]
    
    def build_index(self, documents: List[Dict]):
        """Build inverted index from documents"""
        self.total_docs = len(documents)
        total_length = 0
        
        for doc_id, doc in enumerate(documents):
            # Store metadata
            self.doc_metadata[doc_id] = {
                'title': doc['title'],
                'url': doc['url'],
                'date': doc['date'],
                'language': doc['language']
            }
            
            # Tokenize
            text = doc['title'] + ' ' + doc['body']
            tokens = self.tokenize(text)
            
            # Calculate term frequencies
            term_freq = Counter(tokens)
            self.doc_lengths[doc_id] = len(tokens)
            total_length += len(tokens)
            
            # Add to inverted index
            for term, tf in term_freq.items():
                self.vocabulary.add(term)
                self.index[term].append((doc_id, tf))
        
        self.avg_doc_length = total_length / self.total_docs if self.total_docs > 0 else 0
        print(f"Index built: {self.total_docs} docs, {len(self.vocabulary)} terms")
    
    def get_doc_freq(self, term: str) -> int:
        """Get document frequency for a term"""
        return len(self.index.get(term, []))
    
    def get_postings(self, term: str) -> List[Tuple[int, int]]:
        """Get posting list for a term"""
        return self.index.get(term, [])
    
    def to_dict(self) -> Dict:
        """Convert index to dictionary for JSON export"""
        return {
            'index': {term: postings for term, postings in self.index.items()},
            'doc_lengths': self.doc_lengths,
            'doc_metadata': self.doc_metadata,
            'vocabulary': list(self.vocabulary),
            'total_docs': self.total_docs,
            'avg_doc_length': self.avg_doc_length
        }


class RetrievalModel:
    """Base class for retrieval models"""
    
    def __init__(self, index: InvertedIndex):
        self.index = index
    
    def score_document(self, query_terms: List[str], doc_id: int) -> float:
        """Score a document for given query terms"""
        raise NotImplementedError


class TFIDFRetrieval(RetrievalModel):
    """TF-IDF retrieval model"""
    
    def score_document(self, query_terms: List[str], doc_id: int) -> float:
        score = 0.0
        N = self.index.total_docs
        
        for term in query_terms:
            postings = self.index.get_postings(term)
            df = len(postings)
            
            if df == 0:
                continue
            
            # Calculate IDF
            idf = math.log((N + 1) / (df + 1)) + 1
            
            # Get TF for this document
            tf = 0
            for pid, ptf in postings:
                if pid == doc_id:
                    tf = ptf
                    break
            
            if tf > 0:
                # TF normalization
                tf_normalized = math.log(1 + tf)
                score += tf_normalized * idf
        
        return score


class BM25Retrieval(RetrievalModel):
    """BM25 retrieval model"""
    
    def __init__(self, index: InvertedIndex, k1=1.5, b=0.75):
        super().__init__(index)
        self.k1 = k1
        self.b = b
    
    def score_document(self, query_terms: List[str], doc_id: int) -> float:
        score = 0.0
        N = self.index.total_docs
        avgdl = self.index.avg_doc_length
        doc_len = self.index.doc_lengths.get(doc_id, avgdl)
        
        for term in query_terms:
            postings = self.index.get_postings(term)
            df = len(postings)
            
            if df == 0:
                continue
            
            # IDF component
            idf = math.log((N - df + 0.5) / (df + 0.5) + 1)
            
            # Get TF for this document
            tf = 0
            for pid, ptf in postings:
                if pid == doc_id:
                    tf = ptf
                    break
            
            if tf > 0:
                # BM25 formula
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (1 - self.b + self.b * (doc_len / avgdl))
                score += idf * (numerator / denominator)
        
        return score


class CLIRSystem:
    """Complete Cross-Lingual Information Retrieval System"""
    
    def __init__(self):
        self.scraper = DailyStarScraper()
        self.index = InvertedIndex()
        self.documents = []
        self.retrieval_models = {}
        self.translator = Translator() if TRANSLATION_AVAILABLE else None
        self.embedder = None
        self.search_history = []
        
        if EMBEDDINGS_AVAILABLE:
            print("Loading multilingual embedding model...")
            self.embedder = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
    
    def scrape_and_index(self, max_pages=50):
        """Scrape documents and build index"""
        print("Starting web scraping...")
        self.documents = self.scraper.scrape_multiple(max_pages)
        
        if not self.documents:
            print("No documents scraped. Using sample data...")
            self.documents = self._generate_sample_data()
        
        print(f"Scraped {len(self.documents)} documents")
        print("Building inverted index...")
        self.index.build_index(self.documents)
        
        # Initialize retrieval models
        self.retrieval_models = {
            'tfidf': TFIDFRetrieval(self.index),
            'bm25': BM25Retrieval(self.index)
        }
        
        # Generate embeddings if available
        if self.embedder:
            print("Generating document embeddings...")
            for i, doc in enumerate(self.documents):
                text = doc['title'] + ' ' + doc['body']
                embedding = self.embedder.encode(text)
                doc['word_embeddings'] = embedding.tolist()
    
    def _generate_sample_data(self) -> List[Dict]:
        """Generate sample data for testing"""
        return [
            {
                'title': 'Bangladesh Economy Shows Strong Growth',
                'body': 'The Bangladesh economy continues to grow at a robust pace, driven by strong export performance and remittance inflows. The GDP growth rate reached 7.2% this year, outpacing many regional competitors. Key sectors like textiles, pharmaceuticals, and IT services have contributed significantly to this expansion.',
                'url': 'https://www.thedailystar.net/business/economy/news/bangladesh-economy-growth-2024',
                'date': '2024-12-15',
                'language': 'en',
                'tokens': 185,
                'named_entities': ['Bangladesh', 'GDP', 'IT']
            },
            {
                'title': 'Dhaka Traffic Management System Upgraded',
                'body': 'Dhaka city authorities have implemented a new smart traffic management system to reduce congestion in the capital. The system uses AI-powered cameras and sensors to monitor traffic flow in real-time. Initial results show a 15% reduction in average commute times during peak hours.',
                'url': 'https://www.thedailystar.net/city/news/dhaka-traffic-system-2024',
                'date': '2024-12-14',
                'language': 'en',
                'tokens': 172,
                'named_entities': ['Dhaka', 'AI']
            },
            {
                'title': 'Educational Reform Initiatives Launched',
                'body': 'The government has launched comprehensive educational reform initiatives focusing on digital learning and skills development for students across Bangladesh. The program includes teacher training, infrastructure upgrades, and curriculum modernization to prepare students for the digital economy.',
                'url': 'https://www.thedailystar.net/education/news/education-reform-2024',
                'date': '2024-12-13',
                'language': 'en',
                'tokens': 158,
                'named_entities': ['Bangladesh', 'digital learning']
            },
            {
                'title': 'Renewable Energy Projects Gain Momentum',
                'body': 'Bangladesh is accelerating its transition to renewable energy with several new solar and wind projects announced this quarter. The government aims to generate 40% of electricity from renewable sources by 2030. International partnerships are providing both funding and technical expertise.',
                'url': 'https://www.thedailystar.net/environment/news/renewable-energy-bangladesh-2024',
                'date': '2024-12-12',
                'language': 'en',
                'tokens': 165,
                'named_entities': ['Bangladesh', 'solar', 'wind']
            },
            {
                'title': 'Healthcare Infrastructure Expansion Announced',
                'body': 'Major healthcare infrastructure expansion plans were unveiled today, including 50 new hospitals and 200 community health centers across rural areas. The initiative aims to improve healthcare access for underserved populations and reduce the urban-rural healthcare gap.',
                'url': 'https://www.thedailystar.net/health/news/healthcare-expansion-2024',
                'date': '2024-12-11',
                'language': 'en',
                'tokens': 148,
                'named_entities': ['rural areas']
            }
        ]
    
    def translate_query(self, query: str, source_lang='auto', target_lang='en') -> str:
        """Translate query to target language"""
        if not self.translator:
            return query
        
        try:
            translated = self.translator.translate(query, src=source_lang, dest=target_lang)
            return translated.text
        except Exception as e:
            print(f"Translation error: {e}")
            return query
    
    def search(self, query: str, method='bm25', top_k=10, query_lang='en') -> List[Tuple[int, float, Dict]]:
        """Search documents using specified retrieval method"""
        start_time = time.time()
        
        # Translate query if needed
        original_query = query
        if query_lang != 'en':
            print(f"Translating query from {query_lang} to en...")
            query = self.translate_query(query, source_lang=query_lang, target_lang='en')
            print(f"Translated query: {query}")
        
        # Tokenize query
        query_terms = self.index.tokenize(query)
        
        # Get retrieval model
        model = self.retrieval_models.get(method, self.retrieval_models['bm25'])
        
        # Score all documents
        scores = []
        for doc_id in range(len(self.documents)):
            score = model.score_document(query_terms, doc_id)
            if score > 0:
                scores.append((doc_id, score))
        
        # Sort by score
        scores.sort(key=lambda x: x[1], reverse=True)
        results = scores[:top_k]
        
        elapsed_time = time.time() - start_time
        
        # Store search in history
        search_record = {
            'query': original_query,
            'translated_query': query if query != original_query else None,
            'query_language': query_lang,
            'method': method,
            'num_results': len(results),
            'latency_seconds': elapsed_time,
            'timestamp': datetime.now().isoformat(),
            'results': [
                {
                    'doc_id': doc_id,
                    'score': score,
                    'title': self.index.doc_metadata[doc_id]['title'],
                    'url': self.index.doc_metadata[doc_id]['url']
                }
                for doc_id, score in results
            ]
        }
        self.search_history.append(search_record)
        
        # Return results with metadata
        return [(doc_id, score, self.index.doc_metadata[doc_id]) for doc_id, score in results]
    
    def display_results(self, results: List[Tuple[int, float, Dict]]):
        """Display search results"""
        print(f"\nFound {len(results)} results:\n")
        for rank, (doc_id, score, meta) in enumerate(results, 1):
            print(f"{rank}. [{score:.4f}] {meta['title']}")
            print(f"   Date: {meta['date']}")
            print(f"   URL: {meta['url']}")
            print()
    
    def evaluate_retrieval(self, test_queries: List[Dict]) -> Dict:
        """Evaluate retrieval performance"""
        print("\n=== Retrieval Evaluation ===\n")
        
        evaluation_results = {}
        
        for method_name in ['tfidf', 'bm25']:
            print(f"\nMethod: {method_name.upper()}")
            method_stats = {
                'method': method_name,
                'queries_tested': len(test_queries),
                'query_results': [],
                'total_latency': 0,
                'avg_latency': 0
            }
            
            for query_data in test_queries:
                query = query_data['query']
                start_time = time.time()
                results = self.search(query, method=method_name, top_k=10, query_lang=query_data.get('lang', 'en'))
                elapsed = time.time() - start_time
                method_stats['total_latency'] += elapsed
                
                query_result = {
                    'query': query,
                    'num_results': len(results),
                    'latency_seconds': elapsed,
                    'top_3_docs': [
                        {'title': meta['title'], 'score': score}
                        for _, score, meta in results[:3]
                    ]
                }
                method_stats['query_results'].append(query_result)
                
                print(f"  Query: '{query}' - {len(results)} results in {elapsed:.4f}s")
            
            method_stats['avg_latency'] = method_stats['total_latency'] / len(test_queries) if test_queries else 0
            print(f"  Average latency: {method_stats['avg_latency']:.4f}s")
            
            evaluation_results[method_name] = method_stats
        
        return evaluation_results
    
    def save_complete_data(self, filename='clir_complete_data.json'):
        """Save all system data to a comprehensive JSON file"""
        print(f"\nSaving complete data to {filename}...")
        
        # Prepare complete data structure
        complete_data = {
            'metadata': {
                'system_name': 'Cross-Lingual Information Retrieval System',
                'source_website': 'The Daily Star (thedailystar.net)',
                'export_timestamp': datetime.now().isoformat(),
                'total_documents': len(self.documents),
                'total_vocabulary_terms': len(self.index.vocabulary),
                'embeddings_enabled': EMBEDDINGS_AVAILABLE and self.embedder is not None,
                'translation_enabled': TRANSLATION_AVAILABLE and self.translator is not None
            },
            'documents': [
                {
                    'doc_id': idx,
                    'title': doc['title'],
                    'body': doc['body'],
                    'url': doc['url'],
                    'date': doc['date'],
                    'language': doc['language'],
                    'tokens': doc['tokens'],
                    'named_entities': doc['named_entities'],
                    'word_embeddings': doc.get('word_embeddings', None)
                }
                for idx, doc in enumerate(self.documents)
            ],
            'inverted_index': self.index.to_dict(),
            'index_statistics': {
                'total_documents': self.index.total_docs,
                'vocabulary_size': len(self.index.vocabulary),
                'average_document_length': self.index.avg_doc_length,
                'total_postings': sum(len(postings) for postings in self.index.index.values()),
                'top_20_frequent_terms': self._get_top_terms(20)
            },
            'search_history': self.search_history,
            'retrieval_models': {
                'tfidf': {
                    'name': 'TF-IDF',
                    'description': 'Term Frequency-Inverse Document Frequency'
                },
                'bm25': {
                    'name': 'BM25',
                    'description': 'Best Match 25 (Okapi BM25)',
                    'parameters': {
                        'k1': 1.5,
                        'b': 0.75
                    }
                }
            }
        }
        
        # Save to file
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(complete_data, f, indent=2, ensure_ascii=False)
        
        # Calculate file size
        import os
        file_size = os.path.getsize(filename)
        file_size_mb = file_size / (1024 * 1024)
        
        print(f"✓ Complete data saved successfully!")
        print(f"  File: {filename}")
        print(f"  Size: {file_size_mb:.2f} MB")
        print(f"  Documents: {len(self.documents)}")
        print(f"  Search history entries: {len(self.search_history)}")
    
    def _get_top_terms(self, n=20) -> List[Dict]:
        """Get top N most frequent terms across all documents"""
        term_doc_freq = [(term, len(postings)) for term, postings in self.index.index.items()]
        term_doc_freq.sort(key=lambda x: x[1], reverse=True)
        return [
            {'term': term, 'document_frequency': freq}
            for term, freq in term_doc_freq[:n]
        ]
    
    def save_index(self, filename='clir_index.json'):
        """Save index and documents to file (legacy method)"""
        data = {
            'documents': self.documents,
            'stats': {
                'total_docs': self.index.total_docs,
                'total_terms': len(self.index.vocabulary),
                'avg_doc_length': self.index.avg_doc_length
            }
        }
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Index saved to {filename}")


def main():
    """Main execution function"""
    print("=" * 60)
    print("Cross-Lingual Information Retrieval System")
    print("The Daily Star (thedailystar.net)")
    print("=" * 60)
    print()
    
    # Initialize system
    clir = CLIRSystem()
    
    # Scrape and index (using sample data for demo)
    clir.scrape_and_index(max_pages=50)
    
    # Display index statistics
    print(f"\n=== Index Statistics ===")
    print(f"Total documents: {clir.index.total_docs}")
    print(f"Vocabulary size: {len(clir.index.vocabulary)}")
    print(f"Average document length: {clir.index.avg_doc_length:.2f} tokens")
    
    # Test queries
    test_queries = [
        {'query': 'Bangladesh economy growth', 'lang': 'en'},
        {'query': 'Dhaka traffic congestion', 'lang': 'en'},
        {'query': 'education reform digital', 'lang': 'en'},
        {'query': 'renewable energy solar', 'lang': 'en'},
        {'query': 'healthcare infrastructure', 'lang': 'en'}
    ]
    
    # Evaluate different retrieval methods
    evaluation_results = clir.evaluate_retrieval(test_queries)
    
    # Perform automatic searches with both methods
    print("\n=== Automatic Searches ===")
    for query_data in test_queries:
        query = query_data['query']
        for method in ['tfidf', 'bm25']:
            results = clir.search(query, method=method, top_k=5)
    
    # Save complete data to JSON automatically
    print("\n" + "=" * 60)
    clir.save_complete_data('daily_star_clir_complete.json')
    
    print("\n✓ System shutdown complete.")
    print(f"✓ All data exported to: daily_star_clir_complete.json")


if __name__ == "__main__":
    main()