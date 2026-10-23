"""Isolate browser I/O so stopping a task never waits for a browser timeout."""
import json
import os
import queue
import signal
import subprocess
import sys
import threading
from pathlib import Path
from . import browser_reader,web_reader


def terminate_job(proc):
    if proc.poll() is not None:return
    try:
        if os.name=='nt':proc.terminate()
        else:os.killpg(proc.pid,signal.SIGTERM)
        try:proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            if os.name=='nt':proc.kill()
            else:os.killpg(proc.pid,signal.SIGKILL)
            proc.wait(timeout=2)
    except ProcessLookupError:pass


def run(kind,url,profile,notify,cancelled,login_complete,**options):
    if cancelled.is_set():raise browser_reader.CaptureCancelled('已停止读取，已有资料保持不变。')
    command=[sys.executable,'--capture-worker'] if getattr(sys,'frozen',False) else [sys.executable,'-m','secretary.capture_worker']
    proc=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                          text=True,encoding='utf-8',start_new_session=True,cwd=str(Path(__file__).resolve().parent.parent))
    events=queue.Queue();finished=threading.Event()
    def receive():
        try:
            for line in proc.stdout:
                try:events.put(json.loads(line))
                except ValueError:continue
        finally:finished.set()
    listener=threading.Thread(target=receive,daemon=True);listener.start()
    try:
        proc.stdin.write(json.dumps(dict(kind=kind,url=url,profile=str(profile),options=options),ensure_ascii=False)+'\n');proc.stdin.flush()
        while True:
            if cancelled.is_set():raise browser_reader.CaptureCancelled('已停止读取，已有资料保持不变。')
            if login_complete.is_set():
                login_complete.clear();proc.stdin.write('{"confirm":true}\n');proc.stdin.flush()
            try:event=events.get(timeout=.1)
            except queue.Empty:
                if finished.is_set() and proc.poll() is not None:raise RuntimeError('浏览器读取进程已结束，请重试。')
                continue
            if event.get('type')=='notify':notify(event['state'],event['message'])
            elif event.get('type')=='result':return event['result']
            elif event.get('type')=='error':raise RuntimeError(event['message'])
    finally:
        terminate_job(proc)
        proc.stdin.close();listener.join(timeout=1);proc.stdout.close()


def main():
    request=json.loads(sys.stdin.readline());cancelled=threading.Event();confirmed=threading.Event()
    def commands():
        for line in sys.stdin:
            try:
                if json.loads(line).get('confirm'):confirmed.set()
            except ValueError:pass
    threading.Thread(target=commands,daemon=True).start()
    def send(event):print(json.dumps(event,ensure_ascii=False),flush=True)
    def notify(state,message):send(dict(type='notify',state=state,message=message))
    try:
        read=browser_reader.read if request['kind']=='chatgpt' else web_reader.read
        result=read(request['url'],request['profile'],notify,cancelled,login_complete=confirmed,**request['options'])
        send(dict(type='result',result=result))
    except Exception as error:send(dict(type='error',message=str(error)[:1600]))

if __name__=='__main__':main()
