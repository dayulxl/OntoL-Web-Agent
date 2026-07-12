
import json
html = json.load(open('d:/langchain/_dict_payload.json', encoding='utf-8'))
with open('d:/langchain/webAPP/templates/pages/dictionary.html', 'w', encoding='utf-8') as f:
    f.write(html)
print('done')
