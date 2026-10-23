"""UI labels only. Archived text, titles and summaries are never translated here."""
import json
import re
from functools import lru_cache
from pathlib import Path

@lru_cache(maxsize=1)
def catalogue():
    return json.loads((Path(__file__).parent/'static/locales.json').read_text(encoding='utf-8'))

@lru_cache(maxsize=1)
def pattern():
    return re.compile('|'.join(re.escape(key) for key in sorted(catalogue(),key=len,reverse=True)))

def translate(text,language='zh'):
    if language!='en' or not isinstance(text,str):return text
    messages=catalogue()
    return messages.get(text) if text in messages else pattern().sub(lambda match:messages[match.group()],text)
