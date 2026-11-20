"""Summary preference and language detection for archived material."""
import re
from contextlib import contextmanager
from contextvars import ContextVar

MODES = ('auto', 'zh', 'en')
_preference = ContextVar('summary_language_preference', default=('zh', 'zh'))
output = ContextVar('summary_output_language', default=None)


@contextmanager
def preferences(settings):
    token = _preference.set((settings['summary_language'], settings['ui_language']))
    try:
        yield
    finally:
        _preference.reset(token)


def detect(source):
    # File names, URLs and archival labels can be in a different language from the body.
    source = re.sub(r'https?://\S+|\[第 \d+ 页\]', ' ', source[:100000])
    source = re.sub(r'(?m)^【(?:部分对话归档|网页已加载内容归档|(?:大 )?PDF 前部概览[^】]*|来源链接 [^】]*)】[^\n]*', ' ', source)
    source = re.sub(r'(?im)^附件文字概览：$|^[^\n]{1,255}\.(?:pdf|docx?|txt|png|jpe?g|webp|heic)[ \t]*$', ' ', source)
    han = len(re.findall(r'[\u3400-\u9fff\uf900-\ufaff]', source))
    latin = len(re.findall(r"[A-Za-z]{2,}(?:'[A-Za-z]+)?", source))
    if han >= 4 and han >= 2 * latin:
        return 'zh'
    if latin >= 3 and latin >= han:
        return 'en'
    return None


def resolve(source):
    mode, interface = _preference.get()
    return mode if mode in ('zh', 'en') else detect(source) or ('en' if interface == 'en' else 'zh')


def run_model(run, prompt, backend, language, **options):
    token = output.set(language)
    try:
        if language == 'en':
            prompt = ('Write the generated title, summary, category, tags, and intermediate notes in English. '
                      'Preserve names, original quotations and commands as needed. Use Chinese only for a separate answer field.\n'
                      + prompt)
        return run(prompt, backend, **options)
    finally:
        output.reset(token)


def scope_text(text, language):
    """Translate app-generated coverage notes while retaining page counts and file names."""
    if language != 'en' or not text:
        return text
    replacements = {
        '【组合资料概览】': '[Grouped material overview]',
        '【追加资料概览】': '[Added material overview]',
        '【图片概览】': '[Image overview]',
        '图片以分析用缩略图读取，原件完整保留。': ' Images are analyzed using previews. The originals are preserved.',
        ' 当前 API 未启用图片输入，仅整理文字，图片原件已保存但未识别。': ' Image input is disabled for this API. The summary covers text only. Original images were saved.',
        ' 附件长文仅分析有界片段，PDF 默认仅概览前 5 页；未覆盖全部文字。': ' Long attachments are sampled. PDF overviews normally cover the first five pages.',
        '【PDF 摘要覆盖页码】': '[PDF pages covered]',
        '仅覆盖列出的已提取文字；未列出页面不作推断。': 'Only extracted text from the listed pages is covered.',
        '【PDF 前 5 页概览】仅基于文件前 5 页可读取文字，未总结后续页面。': '[First five PDF pages] This summary covers readable text from the first five pages.',
        'PDF 仅概览前 5 页可读取文字，未覆盖后续页面；原件完整保留。': 'PDF overview covers readable text from the first five pages. The complete original is preserved.',
        '【PDF 开头概览】未取得页码信息，仅基于正文开头最多 2.4 万字符。': '[PDF opening overview] Page numbers were unavailable. This covers up to the first 24,000 characters.',
        ' 本次仅处理其中前 4 万字符。': ' This summary covers up to the first 40,000 characters.',
        '【PDF 全文摘要】基于全部已提取文字分段整理。': '[Full PDF summary] Covers all extracted text.',
        '【PDF 新增页补充摘要】': '[Summary of newly read PDF pages]',
        '【附用户说明】用户说明与网页正文分开提供。': '[User notes] The user’s notes were supplied separately from the webpage text.',
        '【用户说明归档】仅根据用户提供的说明整理，尚未读取网页正文，不推断页面内容。': '[User notes] This summary covers the user’s notes. Webpage text has not been captured.',
    }
    if text.startswith('【部分对话归档】'):
        details = re.search(r'共\s*(\d+)\s*条消息', text)
        suffix = f' Captured {details[1]} messages.' if details else ''
        if '最近4万字符' in text:
            suffix += ' This summary covers the last 40,000 characters of the captured excerpt.'
        return '[Partial conversation capture] This summary covers only the captured excerpt.' + suffix
    if text.startswith('【网页已加载内容归档】'):
        timestamp = re.search(r'文字快照时间：([^。]+)', text)
        return '[Loaded webpage capture] Covers the visible text at capture time.' + (f' Captured at {timestamp[1]}.' if timestamp else '')
    text = re.sub(r'【(?:大 )?PDF 前部概览：第 ([\d–-]+) 页 / 共 (\d+) 页】', r'[PDF overview: pages \1 of \2]', text)
    text = re.sub(r' 本组 (\d+) 个链接，已读取 (\d+) 个；未读取来源仅保存链接，不推断正文。',
                  r' Captured \2 of \1 links. Unread links were saved as bookmarks.', text)
    for source, translated in replacements.items():
        text = text.replace(source, translated)
    return text
