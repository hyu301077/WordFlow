"""用 Windows 自带的 OCR 识别扫描版 PDF。不上传文件。"""

from __future__ import annotations

import asyncio
import logging
from io import BytesIO
from pathlib import Path

logger = logging.getLogger("wordflow")


class OCRUnavailable(Exception):
    pass


def ocr_pdf(path: Path, max_pages: int = 40) -> tuple[str, str]:
    """返回识别出的文本，以及需要告诉用户的说明。某一页失败不会丢掉其他页。"""
    try:
        import pypdfium2 as pdfium
    except Exception as exc:
        raise OCRUnavailable("没有安装 PDF 渲染组件，无法识别扫描版 PDF。") from exc

    ready, message = engine_status()
    if not ready:
        raise OCRUnavailable(message)
    limit = max(1, int(max_pages or 1))
    document = pdfium.PdfDocument(str(path))
    parts: list[str] = []
    failures = 0
    try:
        total = len(document)
        count = min(total, limit)
        for index in range(count):
            page = document[index]
            bitmap = page.render(scale=2)
            try:
                text = recognize_image(bitmap.to_pil())
            except OCRUnavailable:
                raise
            except Exception:
                logger.exception("第 %s 页 OCR 失败", index + 1)
                failures += 1
                text = ""
            finally:
                bitmap.close()
                page.close()
            text = text.strip()
            if text:
                parts.append(text)
    finally:
        document.close()

    notes: list[str] = []
    if total > count:
        notes.append(f"这份 PDF 有 {total} 页，本次只识别了前 {count} 页。")
    if failures:
        notes.append(f"{failures} 页没有识别成功，其余页面已保留。")
    if parts:
        notes.append("文字层不足，已使用 Windows OCR。识别结果可能有错字，导入后可以在词库里修改。")
    elif not notes:
        notes.append(_missing_text_message())
    return "\n".join(parts), " ".join(notes)


def recognize_image(image) -> str:
    status, message = engine_status()
    if not status:
        raise OCRUnavailable(message)
    return asyncio.run(_recognize(image))


def engine_status() -> tuple[bool, str]:
    try:
        engine = _engine()
    except Exception as exc:
        return False, f"无法使用 Windows OCR：{exc}"
    if engine is None:
        return False, _missing_engine_message()
    language = _value(engine, "recognizer_language")
    tag = _value(language, "language_tag") if language is not None else "系统语言"
    return True, f"Windows OCR 可用（{tag}）。"


def _value(obj, name: str):
    attr = getattr(obj, name)
    return attr() if callable(attr) else attr


def _missing_engine_message() -> str:
    return "系统没有可用的 Windows OCR 语言。请到 Windows 设置的语言选项里添加“光学字符识别”，然后重新扫描。"


def _missing_text_message() -> str:
    return "OCR 没有识别出文字。扫描件需要是较清晰的印刷体；手写或模糊页面可能无法识别。"


def _engine():
    from winrt.windows.globalization import Language
    from winrt.windows.media.ocr import OcrEngine

    for tag in ("en-US", "en-GB", "en"):
        language = Language(tag)
        if OcrEngine.is_language_supported(language):
            engine = OcrEngine.try_create_from_language(language)
            if engine is not None:
                return engine
    return OcrEngine.try_create_from_user_profile_languages()


async def _recognize(image) -> str:
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

    payload = BytesIO()
    image.save(payload, format="PNG")
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    try:
        writer.write_bytes(payload.getvalue())
        await writer.store_async()
        writer.detach_stream()
        stream.seek(0)
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        engine = _engine()
        if engine is None:
            raise OCRUnavailable(_missing_engine_message())
        result = await engine.recognize_async(bitmap)
        lines = []
        for line in _value(result, "lines"):
            words = [text for word in _value(line, "words") if (text := str(_value(word, "text") or "").strip())]
            lines.append(" ".join(words) if words else str(_value(line, "text") or ""))
        joined = "\n".join(line for line in lines if line.strip())
        return joined or str(_value(result, "text") or "")
    finally:
        close = getattr(stream, "close", None)
        if close:
            close()
