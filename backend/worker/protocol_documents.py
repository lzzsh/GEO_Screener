"""Material parsing and private content-addressed storage for protocol extraction."""
import hashlib
import io
import json
import os
from pathlib import Path
from uuid import uuid4

import pdfplumber

MAX_FILE_BYTES = 30 * 1024 * 1024
MAX_TEXT_CHARS = 1_500_000
MAX_PAGES = 300


def document_root():
    return Path(os.environ.get('PROTOCOL_DIR', 'data/protocols')).resolve()


def parse_document(content: bytes, name: str):
    if not content or len(content) > MAX_FILE_BYTES:
        raise ValueError('材料为空或超过 30 MB')
    suffix = Path(name).suffix.lower()
    warnings = []
    if suffix == '.pdf':
        if not content.startswith(b'%PDF-'):
            raise ValueError('文件内容不是 PDF')
        try:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                if len(pdf.pages) > MAX_PAGES:
                    raise ValueError('PDF 超过 300 页，请拆分材料')
                pages = []
                size = 0
                for number, page in enumerate(pdf.pages, 1):
                    text = page.extract_text() or ''
                    size += len(text)
                    if size > MAX_TEXT_CHARS:
                        raise ValueError('提取文本超过容量，请拆分材料')
                    if len(text.strip()) < 30:
                        warnings.append(f'第 {number} 页文本不足，可能需要 OCR 或人工检查')
                    pages.append({'page': number, 'text': text})
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError('PDF 损坏、加密或无法解析') from exc
    elif suffix in {'.txt', '.md'}:
        try:
            text = content.decode('utf-8-sig')
        except UnicodeDecodeError as exc:
            raise ValueError('文本文件须使用 UTF-8 编码') from exc
        if len(text) > MAX_TEXT_CHARS:
            raise ValueError('文本超过容量，请拆分材料')
        pages = [{'page': 1, 'text': text}]
    else:
        raise ValueError('当前支持 PDF、TXT、MD；其他补充材料请先转为 PDF 或 UTF-8 文本')
    if sum(len(p['text'].strip()) for p in pages) < 50:
        raise ValueError('材料没有足够的可搜索文本，请上传 OCR 后的 PDF 或对应文本')
    return pages, warnings


def save_document(content, name, item_id):
    pages, warnings = parse_document(content, name)
    sha256 = hashlib.sha256(content).hexdigest()
    directory = document_root() / str(item_id)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f'{sha256}{Path(name).suffix.lower()}'
    temporary = directory / f'{uuid4().hex}.partial'
    try:
        temporary.write_bytes(content)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {'name': Path(name).name[:256], 'path': str(destination), 'sha256': sha256,
            'pages_json': json.dumps(pages, ensure_ascii=False),
            'warnings_json': json.dumps(warnings, ensure_ascii=False)}


def document_context(documents):
    return {d.id: {'name': d.name, 'reference': d.reference, 'kind': d.kind,
                   'pages': json.loads(d.pages_json)} for d in documents}


def material_chunks(documents, max_chars=18000):
    """All pages are processed, including supplements; never silently truncate."""
    chunks, current, length = [], [], 0
    for doc in documents:
        for page in json.loads(doc.pages_json):
            text = page['text']
            # Overlap long pages so a protocol sentence is not cut at a boundary.
            for offset in range(0, max(1, len(text)), max_chars - 1000):
                part = text[offset:offset + max_chars]
                section = {'document_id': doc.id, 'filename': doc.name, 'kind': doc.kind,
                           'reference': doc.reference, 'page': page['page'], 'text': part}
                if current and length + len(part) > max_chars:
                    chunks.append(current); current, length = [], 0
                current.append(section); length += len(part)
    if current:
        chunks.append(current)
    return chunks
