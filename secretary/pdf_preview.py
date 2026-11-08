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


def info(source):
    import pypdfium2 as pdfium
    with LOCK,ExitStack() as stack:
        input=source if isinstance(source,(Path,bytes)) else stack.enter_context(source.open('rb'))
        doc=stack.enter_context(pdfium.PdfDocument(input));return len(doc)


def inspect(source,start=1,end=5,ocr=False,cancel=None,progress=None):
    """Release PDFium between pages and during OCR so browsing stays responsive."""
    import pypdfium2 as pdfium
    from . import local_ocr
    if type(start) is not int or type(end) is not int or start<1 or end<start or end-start>=10:raise ValueError('每次请选择连续 1–10 页')
    with ExitStack() as stack:
        input=source if isinstance(source,(Path,bytes)) else stack.enter_context(source.open('rb'))
        with LOCK:doc=pdfium.PdfDocument(input);total=len(doc)
        try:
            if start>total:raise ValueError('起始页超过文件总页数')
            result=[];end=min(end,total)
            for number in range(start,end+1):
                if cancel and cancel():raise ValueError('页面读取已停止')
                if progress:progress(number-start,end-start+1,number)
                with LOCK,closing(doc[number-1]) as page:
                    if ocr:
                        width,height=page.get_size();scale=min(2,2000/max(width,height))
                        with closing(page.render(scale=scale)) as bitmap:image=bitmap.to_pil().copy()
                    else:
                        with closing(page.get_textpage()) as textpage:
                            count=textpage.count_chars();text=textpage.get_text_range(count=min(count,CHARS_PER_PAGE)) if count else ''
                if ocr:
                    with image:text=local_ocr.recognize(image)
                if cancel and cancel():raise ValueError('页面读取已停止')
                result.append({'page':number,'text':text[:CHARS_PER_PAGE].strip(),'method':'ocr' if ocr else 'text'})
                if progress:progress(number-start+1,end-start+1,number)
            return {'total':total,'start':start,'end':end,'pages':result,'ocr':bool(ocr)}
        finally:
            with LOCK:doc.close()


def page_image(source,number):
    import pypdfium2 as pdfium
    import io
    if type(number) is not int or number<1:raise ValueError('页码无效')
    with LOCK,ExitStack() as stack:
        input=source if isinstance(source,(Path,bytes)) else stack.enter_context(source.open('rb'))
        doc=stack.enter_context(pdfium.PdfDocument(input))
        if number>len(doc):raise ValueError('页码超过文件范围')
        with closing(doc[number-1]) as page:
            width,height=page.get_size()
            with closing(page.render(scale=min(2,1600/max(width,height)))) as bitmap:
                output=io.BytesIO();bitmap.to_pil().save(output,'PNG');return output.getvalue()
