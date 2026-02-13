import json

input_file = 'ModuleA/Data/newagebd_articles.jsonl'
output_file = 'ModuleA/Data/newagebd_articles.json'

with open(input_file, 'r', encoding='utf-8') as infile, \
     open(output_file, 'w', encoding='utf-8') as outfile:
    
    outfile.write('[\n')
    first = True
    
    for line in infile:
        if line.strip():
            if not first:
                outfile.write(',\n')
            obj = json.loads(line)
            json.dump(obj, outfile, ensure_ascii=False)
            first = False
    
    outfile.write('\n]')

print("Conversion complete.")
