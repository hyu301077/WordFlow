"""从助教 Page 读取日期记录，并把文章选区插入待练区。"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from urllib.parse import urlsplit


_PAGE_ID = r"page_[A-Za-z0-9_-]+"
_HEADING = re.compile(r"(#{1,6})[ \t]+([^\n]+)")
_MATERIALS = "# 待练材料"


def parse_page_id(value: str) -> str:
    value = value.strip()
    if re.fullmatch(_PAGE_ID, value):
        return value
    url = urlsplit(value)
    if url.scheme == "https" and url.netloc.lower() == "chatgpt.com":
        match = re.fullmatch(rf"/space/({_PAGE_ID})/?", url.path)
        if match:
            return match[1]
    raise ValueError("请输入 chatgpt.com 的完整 Page 链接或以 page_ 开头的 Page ID。")


def _read(transport, page_id: str) -> dict:
    result = transport.call("chatgpt_space.read_page", {
        "page_id": page_id, "view": "editing", "stream_kind": "content", "include_content": True,
    })
    if "error" in result:
        raise RuntimeError(result["error"].get("message") or "无法读取学习 Page。")
    content = result.get("content", {})
    blocks = content.get("blocks")
    if (content.get("page_id") != page_id or not isinstance(blocks, list)
            or result.get("view", "editing") != "editing" or "excerpt_selection" in result
            or result.get("metadata", {}).get("stream_kind", "content") != "content"
            or not result.get("selection", {}).get("whole_page_complete", True)):
        raise RuntimeError("Pages 没有返回目标页面的完整正文。")
    if any(not b.get("id") or b.get("kind") not in {"markdown", "agent_instructions"}
           or not isinstance(b.get("markdown"), str) for b in blocks):
        raise RuntimeError("Page 中有无法确认标识或内容的段落。")
    return content


def read_records(transport, page_id: str) -> list[dict]:
    blocks = _read(transport, parse_page_id(page_id))["blocks"]
    records = []
    day = None
    day_level = 0
    for block in blocks:
        if block.get("kind") != "markdown":
            continue
        markdown = block["markdown"].strip()
        heading = _HEADING.fullmatch(markdown)
        if heading:
            level, label = len(heading[1]), heading[2].strip()
            if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", label):
                try:
                    day = date.fromisoformat(label).isoformat()
                except ValueError:
                    day = None
                day_level = level
                continue
            if level <= day_level or markdown == _MATERIALS:
                day = None
        if day and markdown:
            records.append({"block_id": block["id"], "day": day, "content": markdown})
    return records


def _material_start(blocks: list[dict]) -> int:
    """返回待练区标题之后的位置；没有标题时从 Page 开头新建。"""
    return next((i + 1 for i, block in enumerate(blocks) if block["markdown"] == _MATERIALS), 0)


def _is_current_passage(blocks: list[dict], source: str, fingerprint: str, text: str) -> bool:
    start = _material_start(blocks)
    if not start or start + 1 >= len(blocks):
        return False
    heading, body = blocks[start:start + 2]
    if (heading.get("metadata") or {}).get("wordflow_passage") != fingerprint and heading["markdown"] != source:
        return False
    # Markdown 的保存过程可能改用不同长度的围栏，比较其中的原文。
    lines = body["markdown"].split("\n")
    fence = re.fullmatch(r"(`{3,}|~{3,})[^`~]*", lines[0])
    return bool(fence and lines[-1].strip() == fence[1] and "\n".join(lines[1:-1]) == text)


def send_passage(transport, page_id: str, document_id: int, title: str, text: str) -> None:
    page_id = parse_page_id(page_id)
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise ValueError("请先在文章中选中要练习的正文。")
    title_line = " ".join(title.split())
    title_line = re.sub(r"([\\`*_\[\]()<>!|~])", r"\\\1", title_line)
    source = f"词流文章 {document_id} · {title_line}"
    fingerprint = hashlib.sha256(f"{document_id}\0{text}".encode()).hexdigest()
    max_ticks = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, max_ticks + 1)
    passage = [
        {"kind": "markdown", "markdown": source, "metadata": {"wordflow_passage": fingerprint}},
        {"kind": "markdown", "markdown": f"{fence}text\n{text}\n{fence}", "metadata": {"codeWrap": [True]}},
    ]
    for attempt in range(2):
        content = _read(transport, page_id)
        blocks = content["blocks"]
        if _is_current_passage(blocks, source, fingerprint, text):
            return
        insertion = _material_start(blocks)
        units = passage if insertion else [_MATERIALS, *passage]
        at = {
            "kind": "between_blocks",
            "preceding_block_id": blocks[insertion - 1]["id"] if insertion else None,
            "following_block_id": blocks[insertion]["id"] if insertion < len(blocks) else None,
        }
        args = {"page_id": content["page_id"], "stream_kind": "content", "operations": [
            {"op": "insert_markdown", "at": at, "block_units": units},
        ]}
        if content.get("through_sequence") is not None:
            args["base_sequence"] = content["through_sequence"]
        try:
            result = transport.call("chatgpt_space.edit_page", args)
        except (OSError, RuntimeError) as exc:
            if _is_current_passage(_read(transport, page_id)["blocks"], source, fingerprint, text):
                return
            raise RuntimeError(f"未确认材料已保存，请重试。{exc}") from exc
        error = result.get("error", {})
        if error and error.get("commit_status") != "unknown":
            if (attempt == 0 and error.get("code") == "edit_conflict"
                    and error.get("recovery", {}).get("action") == "reread_and_rebuild"):
                continue
            raise RuntimeError(error.get("message") or "Pages 拒绝保存材料。")
        for receipt in result.get("operation_results", []):
            if receipt.get("status", "applied") != "applied" or receipt.get("ignored_reason"):
                raise RuntimeError("Pages 未提交这段材料，请重新同步后再发送。")
        if _is_current_passage(_read(transport, page_id)["blocks"], source, fingerprint, text):
            return
        raise RuntimeError("重新读取 Page 后，未能在待练材料首位确认这段原文，请重试。")
