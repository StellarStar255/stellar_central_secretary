"""Tiny synthetic PDFs for encrypted-file extraction tests; no user documents."""
import io
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject


def pdf_bytes(password=None, pages=1):
    writer=PdfWriter()
    for _ in range(pages):
        page=writer.add_blank_page(width=400,height=200)
        if password is not None:
            font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
            page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
            stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 20 100 Td (Encrypted PDF extraction fixture has readable text.) Tj ET')
            page[NameObject('/Contents')]=writer._add_object(stream)
    if password is not None:writer.encrypt(password,owner_password='owner',algorithm='AES-256')
    output=io.BytesIO();writer.write(output);return output.getvalue()
