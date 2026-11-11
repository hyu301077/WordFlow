"""本地文档解析。某个文件失败时返回错误信息，不抛给整个扫描任务。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class ParsedDocument:
    text: str = ""
    warning: str = ""
    error: str = ""
    scanned_pdf: bool = False


def parse_path(path: Path, ocr_max_pages: int = 40) -> ParsedDocument:
    suffix = path.suffix.lower()
    try:
        if suffix in {".txt", ".md", ".markdown"}:
            return ParsedDocument(text=_read_text(path))
        if suffix == ".docx":
            return ParsedDocument(text=_read_docx(path))
        if suffix == ".pdf":
            return _read_pdf(path, ocr_max_pages=ocr_max_pages)
    except Exception as exc:
        return ParsedDocument(error=f"无法读取：{exc}")
    return ParsedDocument(error=f"暂不支持的文件类型：{suffix}")


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    if not raw:
        return ""
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _read_docx(path: Path) -> str:
    from docx import Document

    document = Document(str(path))
    parts: list[str] = []
    for paragraph in document.paragraphs:
        if paragraph.text.strip():
            parts.append(paragraph.text)
    for table in document.tables:
        for row in table.rows:
            seen: set[str] = set()
            for cell in row.cells:
                value = cell.text.strip()
                if value and value not in seen:
                    seen.add(value)
                    parts.append(value)
    return "\n".join(parts)


def _read_pdf(path: Path, ocr_max_pages: int = 40) -> ParsedDocument:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    if getattr(reader, "is_encrypted", False):
        try:
            reader.decrypt("")
        except Exception:
            return ParsedDocument(error="加密的 PDF 暂不支持")
    pages = list(reader.pages)
    chunks: list[str] = []
    for page in pages:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:
            chunks.append("")
    text = "\n".join(chunks).strip()
    letters = sum(character.isalpha() for character in text)
    sparse = bool(pages) and letters < max(40, len(pages) * 20)
    if not sparse:
        return ParsedDocument(text=text)
    try:
        from wordflow.ocr import OCRUnavailable, ocr_pdf

        ocr_text, ocr_warning = ocr_pdf(path, max_pages=ocr_max_pages)
    except OCRUnavailable as exc:
        ocr_text, ocr_warning = "", str(exc)
    except Exception as exc:
        ocr_text, ocr_warning = "", f"OCR 失败：{exc}"
    ocr_letters = sum(character.isalpha() for character in ocr_text)
    if ocr_letters >= 12 and ocr_letters > letters:
        return ParsedDocument(text=ocr_text, warning=ocr_warning)
    if letters >= 40:
        return ParsedDocument(text=text, warning=ocr_warning or "部分页面文字很少")
    return ParsedDocument(text="", scanned_pdf=True, warning=ocr_warning or "没有识别出足够的英文")
