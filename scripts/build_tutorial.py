"""Build the offline tutorial from the same assets served inside the application."""
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
static=ROOT/'secretary/static'
html=(static/'tutorial.html').read_text(encoding='utf-8')
html=html.replace('<link rel="stylesheet" href="tutorial.css">','<style>\n'+(static/'tutorial.css').read_text(encoding='utf-8')+'\n</style>')
html=html.replace('<script src="tutorial.js"></script>','<script>\n'+(static/'tutorial.js').read_text(encoding='utf-8')+'\n</script>')
(ROOT/'docs/tutorial.html').write_text(html,encoding='utf-8')
print('Built docs/tutorial.html: self-contained, no backend or model required')
