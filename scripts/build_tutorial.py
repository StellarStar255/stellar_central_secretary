"""Build the offline tutorial from the same assets served inside the application."""
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
static=ROOT/'secretary/static'
html=(static/'tutorial.html').read_text(encoding='utf-8')
html=html.replace('<link rel="stylesheet" href="tutorial.css">','<style>\n'+(static/'tutorial.css').read_text(encoding='utf-8')+'\n</style>')
for name in ('i18n-data.js','i18n.js','tutorial.js'):
    html=html.replace('<script src="'+name+'"></script>','<script>\n'+(static/name).read_text(encoding='utf-8')+'\n</script>')
(ROOT/'docs/tutorial.html').write_text(html,encoding='utf-8')
print('Built docs/tutorial.html: self-contained, no backend or model required')
