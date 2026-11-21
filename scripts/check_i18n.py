"""Validate display-language changes, data isolation and both tutorial languages."""
import os,sys,tempfile,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT))
from secretary.server import Service,handler

with tempfile.TemporaryDirectory() as temp:
 service=Service(temp);service.archive.configure('codex',False)
 item,_=service.archive.add('知识库','这段原文叫模型与设置，必须保持原样。')
 service.archive.update(item,summary='保留这段中文摘要',tags=['中文标签'],state='ready')
 before=service.archive.export()
 server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(executable_path=os.environ.get('CHROME_PATH','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),headless=True)
   try:
    page=browser.new_page(viewport={'width':1280,'height':950});errors=[];page.on('pageerror',lambda error:(errors.append(str(error)),print('PAGE ERROR:',error,flush=True)))
    page.goto(base);page.locator('#message-input').fill('未发送的中文草稿');page.locator('#settings-open').click()
    page.locator('#auto-ai').check();page.locator('#ui-language').select_option('en');expect(page.locator('html')).to_have_attribute('lang','en')
    assert 'Models & settings' in page.locator('#settings-open').inner_text()
    assert page.locator('#auto-ai').is_checked(),'unsaved settings must survive language switching'
    assert page.locator('#message-input').input_value()=='未发送的中文草稿'
    assert page.locator('#tutorial-open').get_attribute('href')=='/tutorial?lang=en'
    recovery={'current':'0.1.134','phase':'idle','supported':True,'available':True,
              'recovery':{'kind':'copy','original_install_dir':'D:/Stellar Secretary','has_log':True}}
    page.evaluate('state=>renderUpdate(state)',recovery)
    expect(page.locator('#update-recovery-summary')).to_contain_text('running from a recovery copy')
    expect(page.locator('#update-repair-location')).to_have_text('Original installation folder · D:/Stellar Secretary')
    expect(page.locator('#update-install')).to_be_hidden()
    page.locator('#ui-language').select_option('zh')
    expect(page.locator('#update-recovery-summary')).to_contain_text('已从恢复副本启动旧版')
    expect(page.locator('#update-open-log')).to_have_text('打开更新日志')
    page.locator('#ui-language').select_option('en')
    expect(page.locator('#update-open-log')).to_have_text('Open update log')
    expect(page.locator('#update-repair a')).to_have_text('Download official installer ↗')
    save=page.locator('#settings-save');scroll=page.locator('.settings-scroll')
    assert save.inner_text()=='Save settings'
    for width,height in ((1280,950),(460,540)):
     page.set_viewport_size({'width':width,'height':height})
     scroll.evaluate('(el)=>el.scrollTop=0')
     at_top=save.bounding_box()
     assert at_top and at_top['y']+at_top['height']<=height
     scroll.evaluate('(el)=>el.scrollTop=el.scrollHeight')
     assert scroll.evaluate('(el)=>el.scrollTop')>0
     assert abs(save.bounding_box()['y']-at_top['y'])<1
     expect(save).to_be_in_viewport()
     assert save.evaluate("""button=>{
      const bounds=button.getBoundingClientRect();
      return button.contains(document.elementFromPoint(bounds.x+bounds.width/2,bounds.y+bounds.height/2))
     }""")
    page.set_viewport_size({'width':1280,'height':950})
    page.screenshot(path='/tmp/secretary-english-settings.png')
    save.click();expect(page.locator('#settings-dialog')).not_to_be_visible()
    assert service.archive.settings()['auto_ai'] is True
    assert page.locator('#chat-scroll').bounding_box()['height']>150;page.screenshot(path='/tmp/secretary-english-home.png');page.locator('#library-open').click();page.locator('#items [data-id="'+item+'"]').click()
    page.locator('#preview-full').click();page.locator('#edit-title').wait_for();assert page.locator('#edit-title').inner_text().strip()=='知识库 ✎'
    assert page.locator('#detail-content').get_by_role('heading',name='Summary',exact=True).count()==1
    assert '保留这段中文摘要' in page.locator('#detail-content .detail-text').first.inner_text()
    assert '这段原文叫模型与设置' in page.locator('#detail-content').inner_text()
    page.locator('#detail-dialog .dialog-head button').click();page.locator('#library-dialog .dialog-head button').click()
    page.reload();expect(page.locator('#model-label')).to_have_text('ChatGPT · Codex');expect(page.locator('html')).to_have_attribute('lang','en');page.locator('#settings-open').click();page.locator('#ui-language').select_option('zh');expect(page.locator('html')).to_have_attribute('lang','zh-CN')
    assert '模型与设置' in page.locator('#settings-open').inner_text()
    tutorial=browser.new_page(viewport={'width':1280,'height':1000});tutorial.goto(base+'/tutorial?lang=en')
    assert tutorial.locator('h1').inner_text()=='Learn by trying it yourself.'
    tutorial.locator('#import-sample').click();tutorial.locator('#next').click();tutorial.locator('#practice-search').fill('June Science Monthly');assert tutorial.locator('#search-results .result').count()==1
    tutorial.locator('#next').click();tutorial.locator('#practice-title').click();tutorial.locator('#practice-title-input').fill('My reading list');tutorial.locator('#practice-title-input').press('Enter')
    tutorial.locator('#next').click()
    with tutorial.expect_popup() as opened:tutorial.locator('#practice-open-pdf').click()
    pdf=opened.value;pdf.wait_for_load_state();pdf.close()
    tutorial.locator('#next').click();tutorial.locator('#settings').click();tutorial.locator('#practice-mode').click();assert tutorial.locator('#mode-badge').inner_text()=='Desktop practice'
    tutorial.locator('#next').click();tutorial.locator('#backup').click();assert tutorial.locator('#completion').inner_text()=='Completed 6 / 6'
    tutorial.screenshot(path='/tmp/secretary-english-tutorial.png',full_page=True)
    tutorial.locator('#tutorial-language').select_option('zh');assert tutorial.locator('#completion').inner_text()=='已完成 6 / 6'
    assert tutorial.evaluate('renamedTitle')=='My reading list'
    tutorial.locator('#tutorial-language').select_option('en');assert tutorial.locator('#completion').inner_text()=='Completed 6 / 6'
    tutorial.set_viewport_size({'width':390,'height':844});assert tutorial.evaluate('document.documentElement.scrollWidth<=innerWidth')
    offline=browser.new_page();offline.goto((ROOT/'docs/tutorial.html').as_uri()+'?lang=en');assert offline.locator('h1').inner_text()=='Learn by trying it yourself.'
    assert [{k:v for k,v in item.items() if k!='last_viewed'} for item in service.archive.export()]==[{k:v for k,v in item.items() if k!='last_viewed'} for item in before],'display language must not alter archived content'
    assert service.archive.settings()['ui_language']=='zh','tutorial language must not change real app preference'
    assert not errors,errors
    print('PASS: live Chinese/English switching, saved preference, draft/unsaved-setting preservation, raw titles/text/summaries unchanged, English six-step tutorial, tutorial progress/name retention, offline English and mobile layout')
   finally:browser.close()
 finally:server.shutdown();server.server_close();service.close()
