import json
import os
from pathlib import Path
from datetime import datetime

def merge_json_files(input_folder='.', output_file='merged_documents.json'):
    """
    Merge all JSON files into a single dataset
    
    Args:
        input_folder: Folder containing JSON files
        output_file: Name of output file
    
    Usage:
        python merge_json.py
    """
    
    # Look for both .json and .jsonl files
    json_files = list(Path(input_folder).glob('*.json')) + list(Path(input_folder).glob('*.jsonl'))
    
    if not json_files:
        print("❌ No JSON/JSONL files found!")
        return [], {'total_files': 0, 'total_docs': 0, 'errors': 0, 'by_source': {}}
    
    print(f"🔄 Merging {len(json_files)} JSON files...")
    print("-" * 70)
    
    all_documents = []
    stats = {
        'total_files': len(json_files),
        'total_docs': 0,
        'errors': 0,
        'by_source': {}
    }
    
    for json_file in json_files:
        try:
            print(f"Processing: {json_file.name}...", end=' ')
            documents = []
            
            # Handle JSONL format (one JSON object per line)
            if json_file.suffix == '.jsonl':
                with open(json_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                data = json.loads(line)
                                documents.append(data)
                            except json.JSONDecodeError:
                                continue
            # Handle regular JSON format
            else:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Handle different JSON structures
                if isinstance(data, list):
                    documents = data
                elif isinstance(data, dict):
                    # Check if it's a wrapper with 'articles' or 'documents' key
                    if 'articles' in data:
                        documents = data['articles']
                    elif 'documents' in data:
                        documents = data['documents']
                    elif 'data' in data:
                        documents = data['data']
                    else:
                        # Single document
                        documents = [data]
                else:
                    documents = []
            
            # Add source filename to each document
            source_name = json_file.stem  # filename without extension
            for doc in documents:
                if isinstance(doc, dict):
                    doc['source_file'] = source_name
                    all_documents.append(doc)
            
            # Update stats
            doc_count = len(documents)
            stats['total_docs'] += doc_count
            stats['by_source'][source_name] = doc_count
            
            print(f"✅ {doc_count} documents")
            
        except Exception as e:
            print(f"❌ Error: {e}")
            stats['errors'] += 1
    
    # Save merged file
    print("\n" + "=" * 70)
    print(f"💾 Saving to {output_file}...")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_documents, f, ensure_ascii=False, indent=2)
    
    # Print statistics
    print("\n📊 MERGE STATISTICS:")
    print("-" * 70)
    print(f"Files processed: {stats['total_files']}")
    print(f"Total documents: {stats['total_docs']}")
    print(f"Errors: {stats['errors']}")
    print(f"\nDocuments by source:")
    for source, count in stats['by_source'].items():
        print(f"  {source}: {count}")
    
    print("\n✅ Merge complete!")
    print(f"Output saved to: {output_file}")
    print("=" * 70)
    
    return all_documents, stats

if __name__ == "__main__":
    # Run merge from the ModuleA/Data directory
    documents, stats = merge_json_files(input_folder='.', output_file='merged_articles.jsonl')