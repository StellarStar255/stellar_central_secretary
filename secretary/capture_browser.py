"""Read in a task-owned tab, optionally without activating the browser."""
import json
import os
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
import threading
from . import browser_reader as reader


def create_task_page(browser, session, background):
    context = browser.contexts[0]
    startup = session.get('startup_url')
    cdp = browser.new_browser_cdp_session()
    try:
        if startup:
            for _ in range(50):
                cdp.send('Target.getTargets')
                page = next((p for p in context.pages if p.url == startup and not p.is_closed()), None)
                if page is not None:
                    return page
                time.sleep(.1)
        with context.expect_page(timeout=15000) as opened:
            cdp.send('Target.createTarget', {'url':'about:blank', 'background':bool(background)})
        page = opened.value
        if not background:
            page.bring_to_front()
        return page
    finally:
        cdp.detach()


def read_managed(url, profile_dir, notify, cancelled, timeout, login_complete, background, close_new_tabs, scope='full'):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError('浏览器连接组件未安装，请重新运行启动脚本安装依赖。') from exc
    target = reader.conversation_url(url)
    profile = Path(profile_dir).resolve()
    profile.mkdir(parents=True, exist_ok=True)
    if os.name != 'nt': profile.chmod(0o700)
    notify('opening_browser', '正在后台打开专用浏览器。' if background else '正在打开专用浏览器。')
    marker = 'about:blank#stellar-capture-'+uuid.uuid4().hex
    session = reader.start_or_reuse_browser(marker, profile, cancelled, background=background)
    confirmed = login_complete if login_complete is not None else threading.Event()
    page = None
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(session['websocket'], timeout=15000)
        try:
            if cancelled.is_set(): raise reader.CaptureCancelled('已停止读取。')
            page = create_task_page(browser, session, background)
            page.goto(target, wait_until='domcontentloaded', timeout=45000)
            attempts = 0
            def login(task_page):
                nonlocal attempts
                attempts += 1
                if attempts > 2: raise RuntimeError('仍未确认登录成功，请登录后重新读取。')
                confirmed.clear()
                task_page.bring_to_front()
                notify('waiting_login', '当前需要登录，已显示本次任务的 Chrome 标签页。请手动登录后点击「我已登录，开始读取」。')
                reader.wait_for_manual_login(session.get('process') or SimpleNamespace(poll=lambda:None), confirmed, cancelled, timeout)
                if not reader.same_conversation(task_page.url, target):
                    task_page.goto(target, wait_until='domcontentloaded', timeout=45000)
                notify('confirming_login', '已收到登录确认，继续读取本次任务页面。')
            result = reader.read_from_browser(pw, session, target, notify, cancelled, min(timeout,90),
                         diagnose=lambda report:(profile.parent/'last-capture-diagnostic.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)),
                         capture_page=page, on_login_required=login, browser=browser, scope=scope)
            session['confirmed'] = True
            reader.save_session(profile, session)
            return result
        finally:
            if close_new_tabs:
                # Only this job's page and its unique startup placeholder are owned.
                owned = [page] if page is not None else []
                if session.get('startup_url') == marker:
                    owned += [p for ctx in browser.contexts for p in ctx.pages if p.url == marker]
                for task_page in owned:
                    try:
                        if not task_page.is_closed(): task_page.close()
                    except Exception:
                        pass
