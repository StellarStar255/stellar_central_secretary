"""Retry a stored source from the desktop, without touching browser sessions."""
import argparse
import json
from pathlib import Path
from . import ai, network
from .core import Archive


def retry(archive, item_id):
    # Claim only an idle source. Another retry must not launch a second model call.
    with archive.db() as db:
        changed = db.execute("UPDATE items SET state='processing',error='' WHERE id=? AND state IN ('error','pending','ready') AND length(trim(text))>0", (item_id,)).rowcount
    if not changed:
        raise RuntimeError('该资料正在处理或尚无正文，本次没有重复启动任务。')
    try:
        item = archive.get(item_id)
        archive.update(item_id, **ai.summary_fields(item, archive.settings()['backend']))
    except BaseException as exc:
        archive.update(item_id, state='error', error=str(exc)[:1600] or '摘要任务已中断，可重新运行。')
        raise
    return archive.get(item_id)


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument('--id')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent/'data'
    archive = Archive(root, recover=False)
    candidates = [item for item in archive.list() if item['text_length'] and item['state'] in ('error','pending')]
    item_id = args.id or (candidates[0]['id'] if candidates else None)
    if not item_id:
        print('没有需要重试的摘要。已有资料和正文保持保存。', flush=True)
        return
    diagnostic = {'item_id': item_id, 'backend': archive.settings()['backend']}
    try:
        print('正在检查模型连接；本次只处理已保存的正文。', flush=True)
        diagnostic['route'] = network.describe(network.child_env())
        print('模型连接方式：'+diagnostic['route'], flush=True)
        print('正在生成摘要，最长约 4 分钟…', flush=True)
        item = retry(archive, item_id)
        diagnostic.update(state=item['state'], summary_length=len(item['summary']))
        print(f'摘要已保存：{item["title"]}（{len(item["summary"])} 字符）。请刷新知识秘书页面。', flush=True)
    except Exception as exc:
        diagnostic.update(state='error', error=str(exc)[:1600])
        print(f'摘要未完成：{exc}\n正文仍保存在知识库，无需重新登录或读取。', flush=True)
        raise SystemExit(1)
    finally:
        (root/'last-ai-diagnostic.json').write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    run()
