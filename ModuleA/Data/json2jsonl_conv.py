import ijson
import json

input_file = 'ModuleA/Data/tbs_news_articles.json'
output_file = 'ModuleA/Data/tbs_news_articles.jsonl'

with open(input_file, 'r', encoding='utf-8') as infile, open(output_file, 'w', encoding='utf-8') as outfile:
    # "item" assumes the JSON is a list of objects. 
    # It reads them one by one without loading the whole file.
    objects = ijson.items(infile, 'item')
    
    for obj in objects:
        json.dump(obj, outfile, ensure_ascii=False)
        outfile.write('\n')

print("Conversion complete.")