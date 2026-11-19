"""把截图词表、为目标词生成的例句和本机朗读存入同一个素材包。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from PIL import Image, ImageOps

from wordflow.ai import AIError
from wordflow.ocr import recognize_image
from wordflow.talk_clips import TalkError, _run, ffmpeg_exe, media_duration
from wordflow.tts import SpeechService

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}
_OCR_TILE_SIZE = 3000


def _save_text(path: Path, text: str) -> None:
    temp = path.with_suffix(path.suffix + ".part")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)


def prepare_image(path: Path, folder: Path) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    cache = folder / "ocr.txt"
    if cache.is_file():
        cached = cache.read_text(encoding="utf-8").strip()
        if re.search(r"[A-Za-z]", cached):
            return cached
    with Image.open(path) as original:
        image = ImageOps.exif_transpose(original)
        if image.width > _OCR_TILE_SIZE:
            height = max(1, round(image.height * _OCR_TILE_SIZE / image.width))
            image = image.resize((_OCR_TILE_SIZE, height), Image.Resampling.LANCZOS)
        if "A" in image.getbands() or "transparency" in image.info:
            rgba = image.convert("RGBA")
            image = Image.new("RGB", rgba.size, "white")
            image.paste(rgba, mask=rgba.getchannel("A"))
        else:
            image = image.convert("RGB")
        # Keep long scrolling captures legible by recognizing them in strips.
        parts = [
            recognize_image(image.crop((0, y, image.width, min(y + _OCR_TILE_SIZE, image.height))))
            for y in range(0, image.height, _OCR_TILE_SIZE)
        ]
    lines = []
    for line in "\n".join(parts).splitlines():
        english = re.sub(r"[\u2e80-\u9fff\uf900-\ufaff\uff00-\uffef]+", " ", line)
        if re.search(r"[A-Za-z]", english):
            lines.append(" ".join(english.split()))
    if not lines:
        raise ValueError("截图中未识别到英文，请检查图片是否清晰。")
    text = "\n".join(lines)
    _save_text(cache, text)
    return text


def _generate_examples(client, targets: list[str], known: list[str]) -> dict[str, dict]:
    system = (
        "你教刚开始学习英语的人。为每个目标词写一句简短、能在日常说出口的英文句子和中文翻译。"
        "句中必须使用给定目标词的原形。尽量使用给出的熟词搭配，熟词不够时用最基础的英语。"
        "只返回 JSON 数组，每项有 target、text、translation 三个字符串字段，按目标词顺序。"
    )
    prompt = json.dumps({"目标词": targets, "熟词": known[:40]}, ensure_ascii=False)
    reply = client.complete(system, prompt).strip()
    if reply.startswith("```"):
        reply = "\n".join(reply.splitlines()[1:]).removesuffix("```").strip()
    try:
        data = json.loads(reply)
    except json.JSONDecodeError as exc:
        raise AIError("模型返回的例句格式无法读取。") from exc
    if not isinstance(data, list):
        raise AIError("模型返回的例句格式无法读取。")
    found = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        if not all(isinstance(item.get(key), str) for key in ("target", "text", "translation")):
            continue
        target = item["target"].strip().lower()
        text = item["text"].strip()
        translation = item["translation"].strip()
        if target not in targets or not (0 < len(text) <= 500) or not re.search(r"[\u3400-\u9fff]", translation):
            continue
        if re.search(rf"(?<![A-Za-z]){re.escape(target)}(?![A-Za-z])", text, re.IGNORECASE):
            found[target] = {"target": target, "text": text, "translation": translation}
    return found


def _read_examples(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or any(
        not isinstance(row, dict)
        or not isinstance(row.get("id"), str)
        or not re.fullmatch(r"[0-9]{3,}", row["id"])
        or not all(isinstance(row.get(key), str) and row[key] for key in ("target", "text", "translation"))
        for row in data
    ):
        raise ValueError("截图的例句索引无法读取。")
    return data


def _save_examples(index: Path, rows: list[dict]) -> None:
    _save_text(index, json.dumps(rows, ensure_ascii=False, indent=2))


def _speak_row(service: SpeechService, row: dict, clip_dir: Path) -> float:
    wav, message = service.synthesize(row["text"])
    if wav is None:
        raise TalkError(message or "本机未能生成英文语音。")
    destination = clip_dir / (row["id"] + ".mp3")
    temp = destination.with_suffix(".part")
    try:
        duration = media_duration(wav)
        if duration <= 0:
            raise TalkError("本机没有生成可播放的语音。")
        _run([ffmpeg_exe(), "-y", "-i", str(wav), "-vn", "-ac", "1", "-ar", "44100",
              "-b:a", "128k", "-f", "mp3", str(temp)])
        temp.replace(destination)
        return duration
    finally:
        wav.unlink(missing_ok=True)
        temp.unlink(missing_ok=True)


def enrich_image(
    folder: Path, targets: list[str], known: list[str], client, settings, progress=None, cancelled=None
) -> str:
    report = progress or (lambda message: None)
    clip_dir = folder / "sentences_by_sentence"
    clip_dir.mkdir(parents=True, exist_ok=True)
    index = clip_dir / "index.json"
    rows = _read_examples(index)
    covered = {row["target"] for row in rows}
    targets = list(dict.fromkeys(target.strip().lower() for target in targets if target.strip()))
    missing = [target for target in targets if target not in covered]
    warnings = []
    next_id = max((int(row["id"]) for row in rows), default=0) + 1
    if missing and client is None:
        warnings.append("尚有例句待生成，请配置在线助手并允许向所选服务发送素材文字。")
    elif missing:
        for start in range(0, len(missing), 8):
            if cancelled and cancelled():
                raise InterruptedError("已取消，已生成的例句会保留。")
            batch = missing[start : start + 8]
            report(f"正在生成截图词汇的例句（{start + 1} / {len(missing)}）。")
            try:
                generated = _generate_examples(client, batch, known)
            except AIError as exc:
                warnings.append(str(exc))
                break
            for target in batch:
                if target in generated:
                    rows.append({"id": f"{next_id:03d}", **generated[target], "duration": None})
                    next_id += 1
                    covered.add(target)
            _save_examples(index, rows)
        remaining = len(set(targets) - covered)
        if remaining:
            warnings.append(f"{remaining} 个目标词的例句待补。")
    if not index.exists():
        _save_examples(index, rows)

    pending = []
    for row in rows:
        audio = clip_dir / (row["id"] + ".mp3")
        if not audio.is_file() or not audio.stat().st_size or not row.get("duration"):
            pending.append(row)
    if pending:
        service = SpeechService()
        try:
            service.configure(settings.get("voice_pref", "en-US"), int(settings.get("speech_rate", "0")),
                              int(settings.get("speech_volume", "80")))
            for number, row in enumerate(pending, 1):
                if cancelled and cancelled():
                    raise InterruptedError("已取消，已生成的例句和语音会保留。")
                report(f"正在用本机英语语音朗读例句（{number} / {len(pending)}）。")
                try:
                    row["duration"] = _speak_row(service, row, clip_dir)
                except (OSError, TalkError) as exc:
                    warnings.append(f"{len(pending) - number + 1} 句语音待补。{exc}")
                    break
                _save_examples(index, rows)
        finally:
            service.close()
    return " ".join(warnings)
