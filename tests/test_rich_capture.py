import json
import os
from pathlib import Path
import tempfile
import unittest
from secretary.core import Archive
from secretary.rich_text import searchable_text


class RichTextTest(unittest.TestCase):
    def test_chart_labels_are_searchable_but_drawing_commands_are_not(self):
        chart = {'version':1, 'tree':{'tag':'svg', 'children':[
            {'tag':'path', 'attrs':{'d':'M1234 8765 L9999 8888'}},
            {'tag':'text', 'text':'年度趋势', 'children':[{'tag':'tspan', 'text':'2025'}]}]}}
        source = '前文\n```stellar-chart\n'+json.dumps(chart)+'\n```\n后文'
        plain = searchable_text(source)
        self.assertIn('年度趋势', plain)
        self.assertIn('2025', plain)
        self.assertIn('后文', plain)
        self.assertNotIn('8765', plain)
        with tempfile.TemporaryDirectory() as temp:
            archive = Archive(temp)
            item_id, _ = archive.add('图表资料', source)
            self.assertEqual(archive.get(item_id)['text'], source)
            self.assertTrue(archive.retrieve('年度趋势'))
            self.assertFalse(archive.retrieve('8765'))
            self.assertFalse(archive.list(q='8765'))


@unittest.skipUnless(os.environ.get('SECRETARY_BROWSER_TEST') == '1', 'Opt-in real Chrome fixture test')
class BrowserCaptureTest(unittest.TestCase):
    def test_whole_turn_tables_and_svg_survive_capture_and_render(self):
        from playwright.sync_api import sync_playwright
        from secretary.browser_reader import chrome_executable, message_text
        root = Path(__file__).resolve().parent.parent
        extractor = (root/'secretary/static/extract.js').read_text(encoding='utf-8')
        renderer = (root/'secretary/static/app.js').read_text(encoding='utf-8').split('const $ =')[0]
        fixture = '''<style>body{background:#171717;color:#eee;font:16px sans-serif}svg{display:block}td,th{padding:10px}</style>
        <main><article data-testid="conversation-turn-1" data-turn="user"><div data-message-author-role="user">比较三种方式</div></article>
        <article data-testid="conversation-turn-2" data-turn="assistant">
        <div data-message-author-role="assistant"><p>方案与年度趋势</p>
        <table><tr><th>需求</th><th>方案甲</th><th>方案乙</th></tr><tr><td><strong>自动操作</strong></td><td>支持</td><td>手动</td></tr><tr><td>特殊字符</td><td>A | B</td><td>普通文本</td></tr></table></div>
        <div><p>此图位于回答角色节点之外。</p><svg width="680" height="260" viewBox="0 0 680 260">
        <path d="M60 180 L300 80 L600 120" stroke="#e99a65" fill="none" stroke-width="3"/>
        <text x="60" y="215" fill="white">2023</text><text x="300" y="215" fill="white">2024</text><text x="600" y="215" fill="white">2025</text>
        <text x="60" y="35" fill="white">年度趋势示例</text></svg></div><button>复制</button></article></main>'''
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=chrome_executable(), headless=True)
            try:
                page = browser.new_page(viewport={'width':960, 'height':900}, color_scheme='dark')
                page.set_content(fixture)
                captured = page.evaluate('() => {'+extractor+';return extractKnowledgeConversation();}')
                self.assertEqual(captured['diagnostics']['method'], 'conversation-turn')
                text = captured['messages'][1]['text']
                self.assertIn('| 需求 | 方案甲 | 方案乙 |', text)
                self.assertIn('```stellar-chart', text)
                self.assertNotIn('复制', text)
                self.assertIn('角色节点之外', text)
                page.evaluate(renderer)
                html = page.evaluate('(text) => renderArchivedBody({kind:"link",text})', message_text(captured['messages']))
                page.set_content('<meta charset="utf-8"><style>'+(root/'secretary/static/style.css').read_text()+'</style><div id="detail-content">'+html+'</div>')
                self.assertEqual(page.locator('table tbody tr').count(), 2)
                self.assertEqual(page.locator('table tbody tr').last.locator('td').nth(1).inner_text(), 'A | B')
                self.assertEqual(page.locator('.reader-chart path').count(), 1)
                self.assertEqual(page.locator('.reader-chart text').count(), 4)
                page.screenshot(path='/tmp/secretary-rich-preview.png', full_page=True)
                # Real current ChatGPT structure: search-unit divs and sr-only h4 labels,
                # with neither author-role nodes nor conversation-turn articles.
                page.set_content(fixture)
                page.evaluate("""() => {
                  for(const article of [...document.querySelectorAll('article')]){
                    const role=article.getAttribute('data-turn');
                    const node=document.createElement('div');
                    node.setAttribute('data-chatgpt-search-unit-key','fallback-turn-0:0:'+role);
                    node.setAttribute('data-chatgpt-search-message-ids','fixture-'+role);
                    node.innerHTML=article.innerHTML;
                    for(const author of node.querySelectorAll('[data-message-author-role]'))author.removeAttribute('data-message-author-role');
                    const label=document.createElement('h4');label.className='sr-only';label.textContent=role==='user'?'You said:':'ChatGPT said:';
                    if(role==='assistant')label.setAttribute('data-conversation-role','assistant');
                    node.prepend(label);article.replaceWith(node);
                  }
                  const svg=document.querySelector('svg');
                  const widget=document.createElement('div');widget.setAttribute('data-testid','chatgpt-chart-content-reference');
                  svg.before(widget);widget.innerHTML='<h3>趋势示例</h3><div class="recharts-wrapper"><div class="recharts-legend-wrapper"><button class="Chart_LegendItem"><div class="Chart_LegendItemMarker" style="background:#e99a65"></div><span>方案甲</span></button></div></div><div class="sr-only">2023: 方案甲 10; 2024: 方案甲 20</div>';
                  widget.querySelector('.recharts-wrapper').prepend(svg);
                }""")
                captured = page.evaluate('() => {'+extractor+';return extractKnowledgeConversation();}')
                self.assertEqual(captured['diagnostics']['method'], 'search-unit')
                self.assertEqual(captured['diagnostics']['richCharts'], 1)
                self.assertEqual(captured['diagnostics']['authorNodes'], 0)
                self.assertEqual(captured['diagnostics']['turnNodes'], 0)
                self.assertEqual([m['id'] for m in captured['messages']], ['fixture-user','fixture-assistant'])
                self.assertNotIn('ChatGPT said:', captured['messages'][1]['text'])
                import re
                chart = json.loads(re.search(r'```stellar-chart\n(.*?)\n```', captured['messages'][1]['text'], re.S).group(1))
                self.assertEqual(chart['legend'][0]['label'], '方案甲')
                self.assertEqual(chart['title'], '趋势示例')
                self.assertIn('方案甲 10', chart['dataText'])
                self.assertIn('方案甲 10', searchable_text(captured['messages'][1]['text']))
                page.evaluate("() => document.querySelectorAll('[data-chatgpt-search-unit-key]').forEach(n=>n.removeAttribute('data-chatgpt-search-unit-key'))")
                captured = page.evaluate('() => {'+extractor+';return extractKnowledgeConversation();}')
                self.assertEqual(captured['diagnostics']['method'], 'role-heading-dom')
                self.assertEqual(captured['diagnostics']['richCharts'], 1)

            finally:
                browser.close()


if __name__ == '__main__': unittest.main()
