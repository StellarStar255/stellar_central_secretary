"""Diagnose/read the CURRENT signed-in browser without restarting the app."""
import argparse
import json
import sqlite3
import threading
from pathlib import Path
from . import browser_reader
from .core import Archive


def persist_capture(root,result):
    url=browser_reader.conversation_url(result['url'])
    text=result.get('text','')
    if not isinstance(text,str) or not text.strip() or len(text)>2_000_000:
        raise ValueError('正文为空或超过 200 万字符，未写入知识库。')
    archive=Archive(root,recover=False)
    item_id,created=archive.add(title=result.get('title',''),text=text,url=url)
    if not created:
        if archive.get(item_id)['state'] in ('processing','reading','opening_browser','waiting_login','confirming_login'):
            raise RuntimeError('资料正在处理，本次采集文件已保留，请等待处理结束后重试。')
        archive.replace_capture(item_id,result.get('title',''),text)
    return archive.get(item_id)


def run():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8768)
    parser.add_argument('--url')
    args=parser.parse_args()
    root=Path(__file__).resolve().parent.parent/'data'
    if args.url: target=browser_reader.conversation_url(args.url)
    else:
        with sqlite3.connect(root/'archive.sqlite3') as db:
            rows=db.execute("SELECT url FROM items WHERE url!='' ORDER BY updated DESC").fetchall()
        target=next((row[0] for row in rows if '/c/' in row[0] and 'chatgpt.com' in row[0]),None)
        if not target: raise RuntimeError('知识库中没有可诊断的 ChatGPT 会话链接。')
        target=browser_reader.conversation_url(target)
    profile=root/'browser-live-profile'
    session=browser_reader.existing_session(profile)
    if not session: raise RuntimeError('没有找到仍在运行的专用浏览器。请先在知识秘书中打开浏览器并完成登录。')
    from playwright.sync_api import sync_playwright
    print('正在读取当前已登录窗口，并从顶部到底部补读消息；请暂时不要滚动该窗口。',flush=True)
    def report(value):
        (root/'last-capture-diagnostic.json').write_text(json.dumps(value,ensure_ascii=False,indent=2))
    def notify(state,message): print(message,flush=True)
    with sync_playwright() as pw:
        result=browser_reader.read_from_browser(pw,session,target,notify,threading.Event(),timeout=30,diagnose=report)
    print(f'已取得正文：{result["message_count"]} 条消息，{len(result["text"])} 字符。',flush=True)
    capture=root/'last-capture.knowledge.json'
    capture.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    # Generic URL ingestion deliberately deduplicates existing sources; use the
    # explicit refresh path here so a longer capture actually replaces old text.
    item=persist_capture(root,result)
    print(f'正文已写入知识库：{len(item["text"])} 字符。旧版本备存在 data/capture-history。',flush=True)
    if Archive(root,recover=False).settings()['auto_ai'] and item['state']=='pending':
        from .retry_summary import retry
        print('正在重新生成摘要…',flush=True)
        try:
            item=retry(Archive(root,recover=False),item['id'])
            print('摘要已保存。',flush=True)
        except Exception as exc:
            print(f'正文补读已保存；摘要生成失败：{exc}。可单独重试摘要。',flush=True)
    print('请刷新知识秘书页面。',flush=True)
    session['confirmed']=True;browser_reader.save_session(profile,session)


if __name__=='__main__':
    try:run()
    except Exception as exc:
        print(f'读取未完成：{exc}\n诊断文件：data/last-capture-diagnostic.json\n浏览器窗口保持打开。',flush=True)
        raise SystemExit(1)
