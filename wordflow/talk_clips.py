"""把用户提供的英语视频整理成英文稿、中英对照稿，以及按完整句子切好的 MP3。

英文来自本地识别，不改写内容。中文只在调用方传入在线模型时生成，缺的句子写「待补充」。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

_ABBREVIATIONS = (
    "Mr",
    "Mrs",
    "Ms",
    "Dr",
    "Prof",
    "Sr",
    "Jr",
    "St",
    "Vs",
    "Etc",
    "e.g",
    "i.e",
    "U.S",
    "U.K",
    "U.N",
    "a.m",
    "p.m",
)
_MEDIA = {".mp4", ".mkv", ".mov", ".webm", ".mp3", ".wav", ".m4a", ".aac", ".flac"}
_PLACEHOLDER = "∯"


class TalkError(Exception):
    pass


@dataclass(frozen=True)
class TimedWord:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class Segment:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class Span:
    start: float
    end: float
    text: str
    note: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(frozen=True)
class TalkResult:
    folder: Path
    clips: int
    english_words: int
    chinese_chars: int
    merged: int
    translated: bool
    warning: str = ""


def build_talk(
    source: Path,
    output_root: Path,
    folder_name: str,
    model_size: str,
    model_dir: Path,
    client=None,
    progress=None,
    cancelled=None,
) -> TalkResult:
    source = Path(source)
    if source.suffix.lower() not in _MEDIA or not source.is_file():
        raise TalkError("请选择本机上的英语视频或音频文件。")
    report = progress or (lambda _message: None)
    stop = cancelled or (lambda: False)
    _check_stop(stop)
    folder = allocate_folder(Path(output_root), safe_folder_name(source, folder_name))
    audio_dir = folder / "output"
    clip_dir = folder / "sentences_by_sentence"
    audio_dir.mkdir(parents=True, exist_ok=True)
    clip_dir.mkdir(parents=True, exist_ok=True)
    (folder / "source.txt").write_text(str(source.resolve()), encoding="utf-8")
    wav = folder / "talk.wav"
    _check_stop(stop)
    report("正在抽出音频。")
    extract_wav(source, wav)
    seconds = media_duration(wav)
    report(f"音频约 {format_clock(seconds)}，开始识别英文。第一次使用会下载识别模型，只保存在这台电脑。")
    segments, words = transcribe_wav(wav, model_size, Path(model_dir), report, stop)
    (audio_dir / "word_timeline.json").write_text(
        json.dumps(
            {
                "words": [{"text": word.text, "start": word.start, "end": word.end} for word in words],
                "segments": [{"text": item.text, "start": item.start, "end": item.end} for item in segments],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    full_text = " ".join(item.text.strip() for item in segments if item.text.strip())
    paragraphs = paragraph_groups(segments)
    sentences = split_sentences(full_text)
    spans = align_sentences(sentences, words)
    if not spans:
        spans = [Span(item.start, item.end, item.text) for item in segments if item.text.strip()]
    if not spans:
        raise TalkError("没有从这段音视频里识别出英文。")
    merged, removed = merge_short_spans(spans)
    _check_stop(stop)
    warning = ""
    translated = client is not None
    if translated:
        try:
            translations = translate_spans(client, merged, report, stop)
        except Exception as exc:
            translations = ["待补充"] * len(merged)
            translated = False
            warning = f"中文译文没有完成，已写成「待补充」。{exc}"
    else:
        translations = ["待补充"] * len(merged)
    _check_stop(stop)
    report(f"正在切出 {len(merged)} 段 MP3。")
    export_mp3s(wav, merged, clip_dir, stop)
    _check_stop(stop)
    write_pack(folder, folder.name, paragraphs, merged, translations, translated)
    long_clips = sum(1 for span in merged if span.duration >= 20)
    if long_clips:
        extra = f"有 {long_clips} 段超过 20 秒，仍按完整句子保留。"
        warning = f"{warning} {extra}".strip()
    return TalkResult(
        folder=folder,
        clips=len(merged),
        english_words=len(full_text.split()),
        chinese_chars=count_chinese(translations),
        merged=removed,
        translated=translated,
        warning=warning,
    )


def safe_folder_name(source: Path, preferred: str) -> str:
    raw = (preferred or source.stem).strip()
    cleaned = re.sub(r"[<>:\"/\\|?*\n\r\t]", "", raw).strip(" .")
    return cleaned[:40] or "talk"


def allocate_folder(root: Path, name: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for index in range(1, 100):
        candidate = root / (name if index == 1 else f"{name}-{index}")
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate
    raise TalkError("同名结果太多，请换一个文件夹名称。")


def split_sentences(text: str) -> list[str]:
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return []
    protected = compact
    for abbreviation in _ABBREVIATIONS:
        protected = re.sub(rf"\b{re.escape(abbreviation)}\.", abbreviation.replace(".", _PLACEHOLDER) + _PLACEHOLDER, protected)
    protected = re.sub(r"(?<=\d)\.(?=\d)", _PLACEHOLDER, protected)
    protected = re.sub(r"\b([A-Z])\.", rf"\1{_PLACEHOLDER}", protected)
    parts = re.split(r"(?<=[.!?])\s+", protected)
    return [part.replace(_PLACEHOLDER, ".").strip() for part in parts if part.strip()]


def paragraph_groups(segments: list[Segment], gap: float = 1.2) -> list[str]:
    groups: list[list[str]] = []
    current: list[str] = []
    last_end: float | None = None
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        if current and last_end is not None and segment.start - last_end >= gap:
            groups.append(current)
            current = []
        current.append(text)
        last_end = segment.end
    if current:
        groups.append(current)
    return [" ".join(group) for group in groups]


def align_sentences(sentences: list[str], words: list[TimedWord], margin: float = 0.08) -> list[Span]:
    usable = [word for word in words if _norm(word.text)]
    cursor = 0
    spans: list[Span] = []
    for sentence in sentences:
        needed = [token for token in (_norm(part) for part in sentence.split()) if token]
        if not needed:
            continue
        start_index, end_index = _find_span(usable, cursor, needed)
        if start_index is None:
            if spans:
                previous = spans[-1]
                spans[-1] = Span(previous.start, previous.end, f"{previous.text} {sentence}".strip(), previous.note or "unaligned")
            continue
        start = max(0.0, usable[start_index].start - margin)
        end = usable[end_index].end + margin
        if spans and start < spans[-1].end:
            start = spans[-1].end
        if end <= start:
            end = start + 0.2
        spans.append(Span(start, end, sentence))
        cursor = end_index + 1
    return spans


def merge_short_spans(spans: list[Span], word_limit: int = 3, second_limit: float = 4.0) -> tuple[list[Span], int]:
    original = len(spans)
    merged = _merge_until(spans, lambda span: _word_count(span.text) <= word_limit, "words")
    merged = _merge_until(merged, lambda span: span.duration < second_limit, "time")
    return merged, original - len(merged)


def translate_spans(client, spans: list[Span], progress, cancelled) -> list[str]:
    results = ["待补充"] * len(spans)
    batch = 12
    for offset in range(0, len(spans), batch):
        _check_stop(cancelled)
        chunk = spans[offset : offset + batch]
        progress(f"正在翻译第 {offset + 1}–{offset + len(chunk)} 句，共 {len(spans)} 句。")
        system, user = translation_prompt(offset, chunk)
        parsed = parse_translations(client.complete(system, user, timeout=120), offset, len(chunk))
        results[offset : offset + len(chunk)] = parsed
    return results


def translation_prompt(offset: int, spans: list[Span]) -> tuple[str, str]:
    system = (
        "你是英语学习助手。把每句英文译成简体中文，作为参考译文。"
        "不要添加解释、音标或原文里没有的内容。"
        "严格按编号逐行回答，格式为 [001] 译文。"
        "没有把握时该行只写：[001] 待补充"
    )
    lines = [f"[{offset + index + 1:03d}] {span.text}" for index, span in enumerate(spans)]
    return system, "\n".join(lines)


def parse_translations(text: str, offset: int, count: int) -> list[str]:
    found: dict[int, str] = {}
    for line in text.splitlines():
        match = re.match(r"\s*\[(\d+)\]\s*(.*)", line.strip())
        if not match:
            continue
        body = match.group(2).strip() or "待补充"
        found[int(match.group(1))] = body
    return [found.get(offset + index + 1, "待补充") for index in range(count)]


def write_pack(
    folder: Path,
    title: str,
    paragraphs: list[str],
    spans: list[Span],
    translations: list[str],
    translated: bool,
) -> None:
    output = folder / "output"
    clips = folder / "sentences_by_sentence"
    output.mkdir(parents=True, exist_ok=True)
    clips.mkdir(parents=True, exist_ok=True)
    english = _english_document(title, paragraphs)
    bilingual = _bilingual_document(title, spans, translations, translated)
    (output / "ted_english.md").write_text(english, encoding="utf-8")
    (output / "ted_bilingual.md").write_text(bilingual, encoding="utf-8")
    _write_docx(output / "ted_english.docx", title, english.split("\n\n"))
    _write_docx(output / "ted_bilingual.docx", title, bilingual.split("\n\n"))
    rows = []
    index_lines = ["| 序号 | 开始 | 结束 | 时长 | 英文 | 备注 |", "| --- | --- | --- | --- | --- | --- |"]
    for index, span in enumerate(spans, start=1):
        number = f"{index:03d}"
        rows.append(
            {
                "id": number,
                "file": f"{number}.mp3",
                "n": index,
                "start": round(span.start, 3),
                "end": round(span.end, 3),
                "duration": round(span.duration, 3),
                "text": span.text,
                "note": span.note,
            }
        )
        index_lines.append(
            f"| {number} | {span.start:.2f} | {span.end:.2f} | {span.duration:.2f} | {span.text.replace('|', '/')} | {span.note} |"
        )
    (clips / "index.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    (clips / "index.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")


def export_mp3s(wav: Path, spans: list[Span], clip_dir: Path, cancelled=None) -> None:
    clip_dir.mkdir(parents=True, exist_ok=True)
    for index, span in enumerate(spans, start=1):
        _check_stop(cancelled or (lambda: False))
        number = f"{index:03d}"
        destination = clip_dir / f"{number}.mp3"
        _run(
            [
                ffmpeg_exe(),
                "-y",
                "-i",
                str(wav),
                "-ss",
                f"{span.start:.3f}",
                "-to",
                f"{max(span.end, span.start + 0.2):.3f}",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "44100",
                "-b:a",
                "128k",
                str(destination),
            ]
        )


def extract_wav(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    _run([ffmpeg_exe(), "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "44100", str(destination)])


def media_duration(path: Path) -> float:
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as handle:
                frames = handle.getnframes()
                rate = handle.getframerate() or 1
                return frames / rate
        except (wave.Error, OSError):
            pass
    process = subprocess.run(
        [ffmpeg_exe(), "-i", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_flags(),
    )
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", process.stderr or "")
    if not match:
        return 0.0
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def transcribe_wav(wav: Path, model_size: str, model_dir: Path, progress, cancelled) -> tuple[list[Segment], list[TimedWord]]:
    if model_size not in {"small", "medium"}:
        model_size = "small"
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise TalkError("还没有安装本地识别组件，暂时不能整理视频。") from exc
    model_dir.mkdir(parents=True, exist_ok=True)
    progress("正在加载识别模型。")
    model = WhisperModel(model_size, device="cpu", compute_type="int8", download_root=str(model_dir))
    iterator, _info = model.transcribe(str(wav), language="en", word_timestamps=True, vad_filter=False, beam_size=5)
    segments: list[Segment] = []
    words: list[TimedWord] = []
    for piece in iterator:
        _check_stop(cancelled)
        text = (piece.text or "").strip()
        if text:
            segments.append(Segment(text, float(piece.start), float(piece.end)))
        for word in piece.words or []:
            token = (word.word or "").strip()
            if token:
                words.append(TimedWord(token, float(word.start), float(word.end)))
        progress(f"已识别到 {format_clock(float(piece.end))}。")
    if not segments:
        raise TalkError("没有从这段音视频里识别出英文。")
    return segments, words


def ffmpeg_exe() -> str:
    override = os.environ.get("WORDFLOW_FFMPEG", "").strip()
    if override and Path(override).is_file():
        return override
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
    except ImportError as exc:
        raise TalkError("没有找到 ffmpeg，无法处理视频音频。") from exc
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    if not exe or not Path(exe).is_file():
        raise TalkError("没有找到 ffmpeg，无法处理视频音频。")
    return exe


def count_chinese(lines: list[str]) -> int:
    return sum(len(re.findall(r"[\u4e00-\u9fff]", line)) for line in lines if line.strip() != "待补充")


def format_clock(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 60}:{total % 60:02d}"


def _english_document(title: str, paragraphs: list[str]) -> str:
    body = "\n\n".join(paragraph.strip() for paragraph in paragraphs if paragraph.strip())
    return f"# {title}\n\n以下英文来自自动识别，没有改写。\n\n{body}\n"


def _bilingual_document(title: str, spans: list[Span], translations: list[str], translated: bool) -> str:
    notice = "中文是在线模型给出的参考译文，不会写入词典，也不会当作测验答案。" if translated else "这次没有调用在线助手，中文均记为「待补充」。"
    blocks = [f"# {title}", notice]
    for index, span in enumerate(spans):
        chinese = translations[index].strip() if index < len(translations) and translations[index].strip() else "待补充"
        blocks.append(f"[{index + 1:03d}]\n{span.text}\n\n{chinese}")
    return "\n\n".join(blocks) + "\n"


def _write_docx(path: Path, title: str, blocks: list[str]) -> None:
    from docx import Document

    document = Document()
    document.add_heading(title, level=1)
    for block in blocks:
        text = block.strip()
        if text and text != f"# {title}":
            document.add_paragraph(text)
    document.save(path)


def _merge_until(spans: list[Span], is_short, stage: str) -> list[Span]:
    current = list(spans)
    for _pass in range(20):
        if len(current) <= 1:
            return current
        index = next((position for position, span in enumerate(current) if is_short(span)), None)
        if index is None:
            return current
        current = _absorb(current, index, stage)
    return current


def _absorb(spans: list[Span], index: int, stage: str) -> list[Span]:
    span = spans[index]
    previous = spans[index - 1] if index > 0 else None
    following = spans[index + 1] if index + 1 < len(spans) else None
    if previous is None and following is None:
        return spans
    if previous is None:
        choice = "next"
    elif following is None:
        choice = "prev"
    else:
        choice = _shorter(previous, following, stage)
    if choice == "prev":
        assert previous is not None
        merged = Span(previous.start, span.end, f"{previous.text} {span.text}".strip(), _note(previous.note, span.note, stage))
        return spans[: index - 1] + [merged] + spans[index + 1 :]
    assert following is not None
    merged = Span(span.start, following.end, f"{span.text} {following.text}".strip(), _note(span.note, following.note, stage))
    return spans[:index] + [merged] + spans[index + 2 :]


def _shorter(previous: Span, following: Span, stage: str) -> str:
    if stage == "words":
        compared = _compare(_word_count(previous.text), _word_count(following.text))
        if compared is None:
            compared = _compare(previous.duration, following.duration)
    else:
        compared = _compare(previous.duration, following.duration)
        if compared is None:
            compared = _compare(_word_count(previous.text), _word_count(following.text))
    if compared is None or compared:
        return "prev"
    return "next"


def _compare(left: float, right: float) -> bool | None:
    if abs(left - right) <= 0.001:
        return None
    return left < right


def _note(left: str, right: str, stage: str) -> str:
    label = "merged-short" if stage == "words" else "merged-lt4s"
    seen: list[str] = []
    for note in (left, right, label):
        for part in note.split("; "):
            if part and part not in seen:
                seen.append(part)
    return "; ".join(seen)


def _find_span(words: list[TimedWord], cursor: int, needed: list[str]) -> tuple[int | None, int | None]:
    limit = min(len(words), cursor + max(40, len(needed) * 4))
    best: tuple[int, int, int] | None = None
    for start in range(cursor, limit):
        if _norm(words[start].text) != needed[0]:
            continue
        matched = 0
        last = start
        position = start
        for token in needed:
            found = None
            for index in range(position, min(len(words), start + len(needed) + 4)):
                if _norm(words[index].text) == token:
                    found = index
                    break
            if found is None:
                break
            matched += 1
            last = found
            position = found + 1
        if matched == len(needed):
            return start, last
        if best is None or matched > best[0]:
            best = (matched, start, last)
    if best and best[0] >= max(1, int(len(needed) * 0.6)):
        return best[1], best[2]
    return None, None


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9']", "", text.lower())


def _word_count(text: str) -> int:
    return len(text.split())


def _check_stop(cancelled) -> None:
    if cancelled():
        raise TalkError("已取消。")


def _run(command: list[str]) -> None:
    process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_flags(),
    )
    if process.returncode != 0:
        lines = [line.strip() for line in (process.stderr or process.stdout or "").splitlines() if line.strip()]
        detail = lines[-1] if lines else "未知错误"
        raise TalkError(f"处理音频失败：{detail}")


def _flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
