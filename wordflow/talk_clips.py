"""把用户提供的英语视频整理成英文稿、中英对照稿，以及按完整句子切好的 MP3。

英文来自本地识别，不改写内容。中文只在调用方传入在线模型时生成，缺的句子写「待补充」。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import wave
from dataclasses import asdict, dataclass
from pathlib import Path

from wordflow.paths import is_frozen

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
MEDIA_EXTENSIONS = frozenset({".mp4", ".mkv", ".mov", ".webm", ".mp3", ".wav", ".m4a", ".aac", ".flac"})
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
    full_text: str = ""
    pending_translations: int = 0


@dataclass
class _TalkMaterial:
    title: str
    paragraphs: list[str]
    spans: list[Span]
    translations: list[str]
    merged: int

    def save(self, folder: Path) -> None:
        _write_json(folder / "output" / "material_talk.json", asdict(self))

    @classmethod
    def read(cls, folder: Path):
        data = json.loads((folder / "output" / "material_talk.json").read_text(encoding="utf-8"))
        data["spans"] = [Span(**row) for row in data["spans"]]
        return cls(**data)


def _write_json(path: Path, data) -> None:
    _write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def _write_text(path: Path, content: str) -> None:
    if path.is_file() and path.read_text(encoding="utf-8") == content:
        return
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(content, encoding="utf-8")
    temp.replace(path)


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
    if source.suffix.lower() not in MEDIA_EXTENSIONS or not source.is_file():
        raise TalkError("请选择本机上的英语视频或音频文件。")
    _check_stop(cancelled or (lambda: False))
    folder = allocate_folder(Path(output_root), safe_folder_name(source, folder_name))
    return prepare_material_talk(source, folder, model_size, model_dir, client, progress, cancelled, title=folder.name)


def prepare_material_talk(
    source: Path, folder: Path, model_size: str, model_dir: Path,
    client=None, progress=None, cancelled=None, *, title: str = "",
) -> TalkResult:
    """在该来源专属的目录继续处理，保留已完成的识别、原声片段和译文。"""
    source, folder = Path(source), Path(folder)
    report = progress or (lambda _message: None)
    stop = cancelled or (lambda: False)
    _check_stop(stop)
    audio_dir = folder / "output"
    clip_dir = folder / "sentences_by_sentence"
    audio_dir.mkdir(parents=True, exist_ok=True)
    if source.is_file():
        if source.suffix.lower() not in MEDIA_EXTENSIONS:
            raise TalkError("请选择本机上的英语视频或音频文件。")
        _write_text(folder / "source.txt", str(source.resolve()))
    wav = folder / "talk.wav"
    if (audio_dir / "material_talk.json").is_file():
        material = _TalkMaterial.read(folder)
    else:
        timeline = audio_dir / "word_timeline.json"
        if timeline.is_file():
            saved = json.loads(timeline.read_text(encoding="utf-8"))
            segments = [Segment(**row) for row in saved["segments"]]
            words = [TimedWord(**row) for row in saved["words"]]
        else:
            _ensure_wav(source, wav, report)
            seconds = media_duration(wav)
            report(f"音频约 {format_clock(seconds)}，正在准备本地英文识别。")
            segments, words = transcribe_wav(wav, model_size, Path(model_dir), report, stop)
            _write_json(timeline, {"words": [asdict(word) for word in words], "segments": [asdict(s) for s in segments]})
        paragraphs = paragraph_groups(segments)
        spans = align_sentences(split_sentences(" ".join(paragraphs)), _clip_timeline(segments, words))
        if not spans:
            raise TalkError("没有从这段音视频里识别出英文。")
        merged, removed = merge_short_spans(spans)
        material = _TalkMaterial(title or source.stem, paragraphs, merged, ["待补充"] * len(merged), removed)
        material.save(folder)
    _check_stop(stop)
    missing = sum(not _has_audio(clip_dir / f"{n:03d}.mp3") for n in range(1, len(material.spans) + 1))
    if missing:
        _ensure_wav(source, wav, report)
        report(f"正在从原声补齐 {missing} 段 MP3。")
        export_mp3s(wav, material.spans, clip_dir, stop, reuse=True)
    _check_stop(stop)
    return _finish_material(folder, material, client, report, stop)


def _has_audio(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def _ensure_wav(source: Path, wav: Path, progress) -> None:
    if _has_audio(wav):
        return
    if not source.is_file():
        raise TalkError("找不到原始音视频或缓存的原声，请重新选择原文件以补齐材料。")
    progress("正在抽出音频。")
    temp = wav.with_suffix(".part.wav")
    extract_wav(source, temp)
    temp.replace(wav)


def enrich_material_talk(folder: Path, client, progress=None, cancelled=None) -> TalkResult:
    """只补译缺少中文的句子，可在原文件已移动时使用。"""
    folder = Path(folder)
    if not (folder / "output" / "material_talk.json").is_file():
        raise TalkError("尚未完成音视频识别，请先继续导入这份材料。")
    return _finish_material(folder, _TalkMaterial.read(folder), client, progress or (lambda _: None), cancelled or (lambda: False))


def _finish_material(folder: Path, material: _TalkMaterial, client, report, stop) -> TalkResult:
    warning = ""
    _check_stop(stop)
    try:
        if client is not None:
            translate_spans(client, material.spans, report, stop, material.translations, lambda: material.save(folder))
    except _TranslationError as exc:
        warning = f"中文译文未补齐。{exc}"
    finally:
        pending = material.translations.count("待补充")
        export_note = write_pack(folder, material.title, material.paragraphs, material.spans, material.translations, not pending)
        warning = " ".join(filter(None, [warning, export_note]))
    _check_stop(stop)
    if pending and client is not None:
        warning = f"{warning} 尚有 {pending} 句待补译。".strip()
    long_clips = sum(1 for span in material.spans if span.duration >= 20)
    if long_clips:
        extra = f"有 {long_clips} 段超过 20 秒，仍按完整句子保留。"
        warning = f"{warning} {extra}".strip()
    full_text = "\n\n".join(material.paragraphs)
    return TalkResult(
        folder=folder,
        clips=len(material.spans),
        english_words=len(full_text.split()),
        chinese_chars=count_chinese(material.translations),
        merged=material.merged,
        translated=not pending,
        warning=warning,
        full_text=full_text,
        pending_translations=pending,
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
    protected = re.sub(r"""([.!?]["'”’)\]]+)\s+(?=[A-Z0-9"'“‘(])""", r"\1\n", protected)
    parts = re.split(r"(?<=[.!?])\s+|\n", protected)
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


def _clip_timeline(segments: list[Segment], words: list[TimedWord]) -> list[TimedWord]:
    """保留可核对的逐词时间；局部缺词时只退回该识别段的起止时间。"""
    timeline = []
    index = 0
    for segment in segments:
        first = index
        while index < len(words) and (words[index].start + words[index].end) / 2 <= segment.end:
            index += 1
        timed = words[first:index]
        if timed and _norm("".join(word.text for word in timed)) == _norm(segment.text):
            timeline.extend(timed)
        else:
            timeline.append(TimedWord(segment.text, segment.start, segment.end))
    return timeline


def align_sentences(sentences: list[str], words: list[TimedWord], margin: float = 0.08) -> list[Span]:
    """只在句末与时间戳同时存在的位置剪切，避免缺词时输出错配的音频。"""
    if not sentences or not words:
        return []
    sentence_text = [_norm(sentence) for sentence in sentences]
    timed = [(word, _norm(word.text)) for word in words]
    if "".join(sentence_text) != "".join(token for _, token in timed):
        return []
    ends = {}
    offset = 0
    for index, text in enumerate(sentence_text):
        offset += len(text)
        ends[offset] = index + 1
    spans: list[Span] = []
    offset = first_sentence = 0
    start = None
    for word, token in timed:
        if not token:
            continue
        if start is None:
            start = word.start
        offset += len(token)
        last = ends.get(offset)
        if last is not None:
            text = " ".join(sentences[first_sentence:last])
            spans.append(Span(start, word.end, text))
            first_sentence = last
            start = None
    padded = []
    for index, span in enumerate(spans):
        left = (spans[index - 1].end + span.start) / 2 if index else 0.0
        right = (span.end + spans[index + 1].start) / 2 if index + 1 < len(spans) else span.end + margin
        padded.append(Span(max(left, span.start - margin), min(right, span.end + margin), span.text))
    return padded


def merge_short_spans(spans: list[Span], word_limit: int = 3, second_limit: float = 4.0) -> tuple[list[Span], int]:
    original = len(spans)
    merged = _merge_until(spans, lambda span: _word_count(span.text) <= word_limit, "words")
    merged = _merge_until(merged, lambda span: span.duration < second_limit, "time")
    return merged, original - len(merged)


class _TranslationError(TalkError):
    pass


def translate_spans(client, spans: list[Span], progress, cancelled, results=None, save=None) -> list[str]:
    if results is None:
        results = ["待补充"] * len(spans)
    offset = 0
    while offset < len(spans):
        _check_stop(cancelled)
        if results[offset] != "待补充":
            offset += 1
            continue
        end = offset + 1
        while end < min(offset + 12, len(spans)) and results[end] == "待补充":
            end += 1
        chunk = spans[offset:end]
        progress(f"正在翻译第 {offset + 1}–{end} 句，共 {len(spans)} 句。")
        system, user = translation_prompt(offset, chunk)
        try:
            reply = client.complete(system, user, timeout=120)
            parsed = parse_translations(reply, offset, len(chunk))
        except Exception as exc:
            _check_stop(cancelled)
            raise _TranslationError(str(exc)) from exc
        results[offset:end] = [line if count_chinese([line]) else "待补充" for line in parsed]
        if save:
            save()
        offset = end
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
) -> str:
    output = folder / "output"
    clips = folder / "sentences_by_sentence"
    output.mkdir(parents=True, exist_ok=True)
    clips.mkdir(parents=True, exist_ok=True)
    english = _english_document(title, paragraphs)
    bilingual = _bilingual_document(title, spans, translations, translated)
    notes = [
        _write_transcript(output / "ted_english.md", title, english),
        _write_transcript(output / "ted_bilingual.md", title, bilingual),
    ]
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
                "translation": translations[index - 1] if index <= len(translations) else "待补充",
                "note": span.note,
            }
        )
        index_lines.append(
            f"| {number} | {span.start:.2f} | {span.end:.2f} | {span.duration:.2f} | {span.text.replace('|', '/')} | {span.note} |"
        )
    _write_json(clips / "index.json", rows)
    _write_text(clips / "index.md", "\n".join(index_lines) + "\n")
    return " ".join(filter(None, notes))


def export_mp3s(wav: Path, spans: list[Span], clip_dir: Path, cancelled=None, *, reuse: bool = False) -> None:
    clip_dir.mkdir(parents=True, exist_ok=True)
    for index, span in enumerate(spans, start=1):
        _check_stop(cancelled or (lambda: False))
        number = f"{index:03d}"
        destination = clip_dir / f"{number}.mp3"
        if reuse and _has_audio(destination):
            continue
        temp = clip_dir / f".{number}.part"
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
                "-f",
                "mp3",
                str(temp),
            ]
        )
        temp.replace(destination)


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


def _whisper_audio(wav: Path, cancelled):
    import numpy as np

    _check_stop(cancelled)
    command = [ffmpeg_exe(), "-nostdin", "-loglevel", "error", "-i", str(wav),
               "-map", "0:a:0", "-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1"]
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=_flags()) as process:
        while True:
            if cancelled():
                process.kill()
                process.communicate()
                raise TalkError("已取消。")
            try:
                audio, errors = process.communicate(timeout=0.3)
                break
            except subprocess.TimeoutExpired:
                continue
    if process.returncode or not audio or len(audio) % 4:
        detail = errors.decode("utf-8", errors="replace").strip()
        raise TalkError(f"原声音频解码失败。{detail or '没有得到可识别的音频。'}")
    return np.frombuffer(audio, dtype="<f4")


def transcribe_wav(wav: Path, model_size: str, model_dir: Path, progress, cancelled) -> tuple[list[Segment], list[TimedWord]]:
    if model_size not in {"small", "medium"}:
        model_size = "small"
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise TalkError("还没有安装本地识别组件，暂时不能整理视频。") from exc
    model_dir.mkdir(parents=True, exist_ok=True)
    candidates = [model_dir / model_size]
    if is_frozen():
        candidates.append(Path(sys.executable).parent / "models" / model_size)
    required = ("model.bin", "config.json", "tokenizer.json")
    local = next((path for path in candidates if all((path / name).is_file() for name in required)), None)
    if local:
        progress(f"正在加载本机识别模型 {model_size}。")
    else:
        progress(f"正在加载识别模型 {model_size}。首次使用需要联网下载。")
    try:
        model = WhisperModel(str(local or model_size), device="cpu", compute_type="int8",
                             download_root=str(model_dir), local_files_only=local is not None)
    except Exception as exc:
        locations = " 或 ".join(str(path) for path in candidates)
        raise TalkError(f"语音识别模型 {model_size} 加载失败。请检查网络，或将完整的离线模型放入 {locations}。{exc}") from exc
    # 直接传入 Whisper 要求的 16 kHz 原声，避开 PyAV 各版本不同的文件解码接口。
    audio = _whisper_audio(wav, cancelled)
    _check_stop(cancelled)
    iterator, _info = model.transcribe(audio, language="en", word_timestamps=True, vad_filter=False, beam_size=5)
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
    notice = "中文是在线模型给出的参考译文。"
    if not translated:
        notice += " 标记为「待补充」的句子可以稍后补译。"
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


def _write_transcript(markdown: Path, title: str, content: str) -> str:
    docx = markdown.with_suffix(".docx")
    docx_temp = markdown.with_suffix(".part.docx")
    if docx.is_file() and not docx_temp.exists() and markdown.is_file() and markdown.read_text(encoding="utf-8") == content:
        return ""
    _write_docx(docx_temp, title, content.split("\n\n"))
    try:
        docx_temp.replace(docx)
    except PermissionError:
        # 暂存文件会让下次重试重新发布 DOCX，即使 Markdown 已经更新。
        _write_text(markdown, content)
        return f"未能更新 {docx.name}，请关闭占用文档的程序后点「补齐素材」。"
    _write_text(markdown, content)
    return ""


def _merge_until(spans: list[Span], is_short, stage: str) -> list[Span]:
    current = list(spans)
    index = 0
    while len(current) > 1 and index < len(current):
        if is_short(current[index]):
            index = _absorb(current, index, stage)
        else:
            index += 1
    return current


def _absorb(spans: list[Span], index: int, stage: str) -> int:
    span = spans[index]
    previous = spans[index - 1] if index > 0 else None
    following = spans[index + 1] if index + 1 < len(spans) else None
    if previous is None:
        choice = "next"
    elif following is None:
        choice = "prev"
    else:
        choice = _shorter(previous, following, stage)
    if choice == "prev":
        assert previous is not None
        merged = Span(previous.start, span.end, f"{previous.text} {span.text}".strip(), _note(previous.note, span.note, stage))
        spans[index - 1 : index + 1] = [merged]
        return index - 1
    assert following is not None
    merged = Span(span.start, following.end, f"{span.text} {following.text}".strip(), _note(span.note, following.note, stage))
    spans[index : index + 2] = [merged]
    return index


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
