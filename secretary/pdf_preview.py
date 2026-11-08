"""Bounded front-page text extraction from disk or a seekable archive member."""
from contextlib import ExitStack,closing
from pathlib import Path
import threading

LOCK=threading.RLock()  # PDFium is not thread-safe, including separate documents.
PAGES=5
CHARS_PER_PAGE=8000
SCOPE='大 PDF 仅概览前 5 页可读取文字，未覆盖后续页面；原件完整保留。'
EMPTY='PDF 前部页面没有可读取文字，可能是扫描件；可补充文字或使用 OCR。'

def read(source):
    import pypdfium2 as pdfium
    try:
        with LOCK,ExitStack() as stack:
            input=source if isinstance(source,(Path,bytes)) else stack.enter_context(source.open('rb'))
            doc=stack.enter_context(pdfium.PdfDocument(input));total=len(doc);count=min(PAGES,total)
            parts=[];truncated=False;failed=False
            for index in range(count):
                try:
                    with closing(doc[index]) as page,closing(page.get_textpage()) as textpage:
                        size=textpage.count_chars();truncated|=size>CHARS_PER_PAGE
                        text=textpage.get_text_range(count=min(size,CHARS_PER_PAGE)).replace('\r\n','\n').strip() if size else ''
                        if text:parts.append(f'[第 {index+1} 页]\n'+text[:CHARS_PER_PAGE])
                except Exception:failed=True
            if not parts:return '',EMPTY
            scope=f'【大 PDF 前部概览：第 1–{count} 页 / 共 {total} 页】'
            warning=SCOPE
            if truncated:warning+=' 每页最多提取 8000 个字符，部分文字已截断。'
            if failed:warning+=' 部分预览页面无法读取。'
            return scope+'\n'+warning+'\n\n'+'\n\n'.join(parts),warning
    except pdfium.PdfiumError as error:
        if error.err_code==4:return '', '此 PDF 需要打开密码，请先使用密码打开并导出可读取版本，再重新导入。'
        return '', 'PDF 文件损坏或结构无法读取，请确认原文件能正常打开后重试。'
    except (OSError,ValueError):return '', 'PDF 文件损坏或结构无法读取，请确认原文件能正常打开后重试。'
