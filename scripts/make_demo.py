"""Record actual app interactions using synthetic documents and a prewritten summary.

Requires a macOS desktop session, Chrome, Playwright and Pillow. No model is called.
Output contains only the isolated example archive, never the installed user's data.
"""
import io
import json
import math
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from secretary.core import Archive

frames=[];durations=[];pointer=[200,200]
with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
base=f'http://127.0.0.1:{port}';opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));token=''
def request(path,body=None):
    req=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json','X-Knowledge-Token':token})
    with opener.open(req,timeout=30) as response:return json.load(response)

def capture(page,milliseconds=800):
    frames.append(Image.open(io.BytesIO(page.screenshot())).convert('RGB').resize((960,600),Image.Resampling.LANCZOS))
    durations.append(milliseconds)

def decorate(page,caption):
    page.evaluate('''caption=>{
      let label=document.querySelector('#demo-caption');if(!label){label=document.createElement('div');label.id='demo-caption';Object.assign(label.style,{position:'fixed',top:'12px',left:'50%',transform:'translateX(-50%)',padding:'9px 16px',borderRadius:'12px',background:'#171918ed',color:'white',margin:'0',border:'0',width:'max-content',right:'auto',bottom:'auto',font:'600 16px -apple-system,BlinkMacSystemFont,sans-serif',zIndex:2147483647,boxShadow:'0 4px 22px #0003',whiteSpace:'nowrap',pointerEvents:'none'});label.popover='manual';document.body.append(label)}label.textContent=caption;if(label.matches(':popover-open'))label.hidePopover();label.showPopover();
      let cursor=document.querySelector('#demo-pointer');if(!cursor){cursor=document.createElement('div');cursor.id='demo-pointer';Object.assign(cursor.style,{position:'fixed',width:'22px',height:'22px',border:'3px solid #e89a5c',borderRadius:'50%',background:'#f5b37d55',margin:'0',padding:'0',right:'auto',bottom:'auto',pointerEvents:'none',zIndex:2147483647,left:'200px',top:'200px',boxShadow:'0 0 0 2px white'});cursor.popover='manual';document.body.append(cursor)}if(cursor.matches(':popover-open'))cursor.hidePopover();cursor.showPopover();
    }''',caption)

def move_to(page,selector):
    locator=page.locator(selector);locator.scroll_into_view_if_needed();box=locator.bounding_box();assert box,selector
    end=[box['x']+box['width']/2,box['y']+box['height']/2];start=pointer.copy()
    for index in range(1,6):
        fraction=index/5;position=[start[n]+(end[n]-start[n])*fraction for n in (0,1)]
        page.evaluate('p=>{const c=document.querySelector("#demo-pointer");if(c.matches(":popover-open"))c.hidePopover();c.showPopover();c.style.left=p[0]+"px";c.style.top=p[1]+"px"}',position)
        capture(page,70)
    pointer[:]=end;return locator

def click(page,selector,hold=650):
    move_to(page,selector).click();capture(page,hold)

def type_text(page,selector,text):
    move_to(page,selector).click()
    for index in range(1,len(text)+1):
        page.locator(selector).fill(text[:index]);capture(page,100)
    page.wait_for_timeout(250)

with tempfile.TemporaryDirectory(prefix='secretary-demo-') as temp:
    env={**os.environ,'SECRETARY_DATA_DIR':temp,'PYTHONPATH':str(ROOT)}
    proc=subprocess.Popen([sys.executable,'-c','from secretary.launcher import main; main()','--desktop','--no-browser','--port',str(port),'--data-dir',temp],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if proc.poll() is not None:raise RuntimeError('Demo host exited')
            try:
                status=request('/api/status')
                if status['desktop'].get('state')=='ready':break
            except OSError:pass
            time.sleep(.2)
        else:raise RuntimeError('Demo host timeout')
        token=status['token'];request('/api/settings',{'backend':'codex','auto_ai':False})
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=os.environ.get('CHROME_PATH','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),headless=True)
            try:
                context=browser.new_context(viewport={'width':1200,'height':750},color_scheme='light',bypass_csp=True)
                page=context.new_page();page.goto(base+'/tutorial');pdf_text=page.evaluate('makePdf()');pdf=Path(temp)/'科学月刊_2026年6月.pdf';pdf.write_text(pdf_text,encoding='ascii')
                page.goto(base);page.locator('#model-label').wait_for();page.wait_for_function('document.querySelector("#model-label").textContent.length>0')
                decorate(page,'知识秘书：存下资料，随时找回');capture(page,1600)
                decorate(page,'① 拖入文件或点「＋」，原件保存在本机')
                move_to(page,'#attach-button');capture(page,500);page.locator('#file-input').set_input_files(pdf);capture(page,1000)
                click(page,'#send-button');page.wait_for_function('document.querySelectorAll(".archive-card").length===1')
                items=request('/api/items');assert len(items)==1;item_id=items[0]['id']
                archive=Archive(temp,recover=False)
                archive.update(item_id,title='科学月刊 · 2026年6月',summary='【PDF 前 5 页概览】教程预置示例：六月月刊介绍月球探索、机器人与清洁能源。原文件已完整保存，可在详情中阅读和下载。',category='科学与技术',tags=['科学月刊','6月','前部概览'],state='ready',error='')
                page.evaluate('refresh()');page.wait_for_function('document.querySelector(".archive-card strong").textContent.includes("科学月刊")')
                decorate(page,'② 原件与概览放在一起（示例摘要已预置）');capture(page,2000)
                click(page,'#library-open');decorate(page,'③ 多个关键词用空格分隔，全部包含、顺序不限')
                type_text(page,'#search','6月 科学月刊');page.wait_for_function('document.querySelectorAll("#items .library-row").length===1');capture(page,1700)
                click(page,'#items .library-row');decorate(page,'④ 点击标题或小铅笔，自己修改名称');capture(page,1100)
                click(page,'#edit-title');type_text(page,'#rename-title','我的六月科学月刊');capture(page,600);click(page,'#save-title');page.wait_for_function('document.querySelector("#edit-title").textContent.includes("我的六月")');capture(page,1300)
                decorate(page,'⑤ 直接在浏览器或系统默认程序中打开 PDF')
                move_to(page,'#open-pdf-browser');capture(page,900)
                with page.expect_popup() as opened:page.locator('#open-pdf-browser').click()
                pdf_page=opened.value;pdf_page.wait_for_load_state();viewer=next((f for f in pdf_page.frames if f.url.startswith('chrome-extension://')),None)
                if viewer is None:viewer=pdf_page.wait_for_event('framenavigated',predicate=lambda frame:frame.url.startswith('chrome-extension://'),timeout=15000)
                viewer.locator('pdf-viewer').wait_for(state='attached');pdf_page.wait_for_timeout(1200)
                decorate(pdf_page,'PDF 原件在新标签页中阅读');capture(pdf_page,2000);pdf_page.close()
                page.locator('#detail-dialog .dialog-head button').click();page.locator('#library-dialog .dialog-head button').click()
                decorate(page,'⑥ 桌面 / 网页切换，收在「模型与设置」里')
                click(page,'#settings-open');move_to(page,'#interface-toggle');capture(page,2000)
                decorate(page,'还有互动教程：跟着示例动手练习，不改动你的资料')
                move_to(page,'#tutorial-open');capture(page,1000)
                with page.expect_popup() as opened:page.locator('#tutorial-open').click()
                tutorial=opened.value;tutorial.wait_for_load_state();tutorial.locator('#import-sample').wait_for()
                decorate(tutorial,'从「模型与设置 → 使用教程」开始练习');capture(tutorial,1400)
                click(tutorial,'#import-sample',500);tutorial.locator('#next').scroll_into_view_if_needed();decorate(tutorial,'跟着示例动手练习，不改动你的知识库');capture(tutorial,2200)
            finally:browser.close()
        request('/api/shutdown',{});proc.wait(timeout=15)
    finally:
        if proc.poll() is None:proc.kill();proc.wait()

# One shared palette keeps text and UI colors stable between frames.
contact=Image.new('RGB',(480*4,300*3),'white')
for index in range(12):
    frame=frames[round(index*(len(frames)-1)/11)].resize((480,300))
    contact.paste(frame,((index%4)*480,(index//4)*300))
palette=contact.quantize(colors=192,method=Image.Quantize.MEDIANCUT)
encoded=[frame.quantize(palette=palette,dither=Image.Dither.NONE) for frame in frames]
output=ROOT/'docs/demo.gif';encoded[0].save(output,save_all=True,append_images=encoded[1:],duration=durations,loop=0,optimize=True,disposal=2)
print(json.dumps({'file':'docs/demo.gif','frames':Image.open(output).n_frames,'duration_seconds':sum(durations)/1000,'size_bytes':output.stat().st_size,'data':'synthetic PDF and prewritten summary; no model called'},ensure_ascii=False))
