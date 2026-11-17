---
name: TED video to sentence clips
description: >-
  Use when the user gives a talk video/audio and wants: (1) a full English
  transcript, (2) a bilingual EN–ZH document, and (3) mp3 clips cut by complete
  sentences—then merge tiny/short clips into neighbors for English study.
---
# TED / talk video → transcripts + sentence mp3s

## Goal
From one user-supplied talk video (or audio), produce:
1. A pure-English transcript document
2. A bilingual English–Simplified-Chinese document
3. Numbered mp3 clips cut on **complete grammar sentences** (not silence/pauses), then **merged** so leftover tiny clips are absorbed into a neighbor

Then tell the user where everything lives.

## WordFlow desktop app

The repo's `wordflow/talk_clips.py` implements local transcription, sentence alignment, short-clip merging, MP3 export, and transcript generation. In the desktop app, open 在线助手 → 视频文案. Output goes to the WordFlow data directory under `talks/`. The first run downloads the speech model. The app sends transcript text for Chinese translation only if the user opts in for that run and has configured the online assistant. Otherwise it marks the Chinese text as 待补充. For an existing virtual environment, install the updated `requirements.txt` first.

Related but different: [Split video into sentence audio](sand-workflow:split-video-into-sentence-audio) cuts on **pauses**. Prefer **this** skill for follow-along / sentence study.

## Inputs
- Source path (chat attachment, box path, or path on their computer).
- Optional short folder name for this talk. If missing and the title is clear, use a **short Chinese** folder name; else a short slug.
- Output root defaults to `/workspace/ted/<talk-folder>/` unless they name another place.
- Optional overrides for merge thresholds (defaults below). If the user only asks to re-merge existing packs, skip ASR and start at step 5.

## Hard limits
- Only process media the user supplies. Do not scrape or bypass blocked video sites.
- Keep work under the talk folder; prefer not to commit huge originals (full mp4/wav ≳95MB) to GitHub—upload sentence mp3s / zip instead if they ask for a repo.
- Transcripts are for the user’s study folder. Do not republish a copyrighted talk script as a public post.

## Working layout
```
/workspace/ted/<talk-folder>/
  talk.mp4 | talk.wav          # source (extract wav if needed)
  output/
    ted_english.md|.docx       # full English
    ted_bilingual.md|.docx     # EN then ZH per unit
    word_timeline_*.json       # optional ASR word times
  sentences_by_sentence/
    001.mp3 …
    index.json | index.md      # #, start, end, duration, English
```
Keep any older pause-based `sentences/` if it already exists; do not overwrite it unless asked.

## Steps

### 1. Set up
- Copy/link the source into the talk folder.
- `ffprobe` duration/codecs; tell the user length and that work started.
- Extract mono wav if needed: `ffmpeg -y -i <source> -vn -ac 1 -ar 44100 talk.wav`.
- Use a venv with `faster-whisper` + `python-docx` (e.g. `/workspace/whenv`). If `av.open(..., metadata_errors=...)` breaks, decode via ffmpeg → float32 16 kHz mono numpy and pass that array to the model.

### 2. Transcribe
- Prefer `medium` + `int8` on CPU (or `small` first if memory is tight, then re-run hard clips).
- **Turn VAD off** for the full-talk pass (`vad_filter=False`). VAD often drops soft speech and breaks later sentence alignment.
- Transcribe the **full** talk with **word timestamps** (save timeline JSON).
- Also keep a clean continuous English text: fix obvious ASR errors, punctuation, casing, proper nouns; do not invent missing content. If the recording ends mid-sentence, mark that (e.g. `[recording ends]`).
- If speaker/title are clear from the audio (self-intro) or a label the user gave, put them at the top of both docs; otherwise omit—do not guess.

### 3. Write the two documents (`output/`)
1. **`ted_english.md`** (+ `.docx`): coherent English article, semantic paragraphs, **no** clip numbers.
2. **`ted_bilingual.md`** (+ `.docx`): after sentence cutting **and merge** (steps 4–5), one entry per **final** clip—English first, then accurate Simplified Chinese; label `[001]`…

   Until clips exist, you may draft bilingual by sentence list in the same order you will cut; after merge, concatenate ZH for absorbed originals in order.

### 4. Split by complete sentences
1. From the English transcript body, split on `.` / `?` / `!` into complete sentences. Preserve short utterances for now (`Yes!`, `Enormous.`). Do not split on periods inside quotes/abbreviations. Skip titles and meta notes.
2. Align each sentence to the word timeline (normalized token match / sliding window). Leave ~50–100 ms margins; estimate audience-only lines from gaps if needed.
3. Export provisional `sentences_by_sentence/NNN.mp3` with `libmp3lame` ~128k between aligned start/end.
4. Write provisional `index.json` and `index.md` (number, start, end, duration, English text).
5. Spot-check several durations with `ffprobe`; if many alignments fail, re-run timeline or fall back to whisper segment times then merge by punctuation.

### 5. Merge short clips (required default)
After the grammar cut, tiny fragments are hard to study alone. **Always** run this merge unless the user asks to keep every grammar sentence separate.

#### Defaults (override only if the user names different numbers)
1. **Word-short:** English word count ≤ **3** (split on whitespace).
2. **Time-short:** clip `duration` (or `end - start`) **&lt; 4.0** seconds.

Run word-short first, then time-short. After each stage, **iterate** until no clip still matches that stage’s rule (cap ~20 passes). If a talk would collapse to a single clip under the threshold, leave that one clip.

#### Neighbor rule (same for both stages)
For short clip `S` at index `i`:
- Only previous exists → merge `S` into previous.
- Only next exists → merge `S` into next.
- Both exist → merge into the **shorter** neighbor:
  - Word-short stage: compare neighbor **word counts**; if equal, compare **duration**; if still equal, prefer previous.
  - Time-short stage: compare neighbor **durations**; if equal, compare **word counts**; if still equal, prefer previous.
- Merge into previous: `start = prev.start`, `end = S.end`, `text = prev.text + " " + S.text`.
- Merge into next: `start = S.start`, `end = next.end`, `text = S.text + " " + next.text`.

Build merge **groups** (chains of shorts absorbed into a chosen neighbor), then emit one span per group: concatenate texts with spaces, `start = min`, `end = max`.

#### Re-cut and refresh
1. From `talk.wav`, re-export contiguous `001.mp3`…`NNN.mp3` for final spans; delete leftover higher-numbered old mp3s.
2. Rewrite `index.json` / `index.md` (preserve schema: `n`+`file` or `id`). Mark merged rows with a note such as `merged-short` / `merged-lt4s`.
3. Rebuild `ted_bilingual.md` (+ `.docx` when practical) to match final clip order; concatenate prior ZH pieces for merged groups when available.
4. Do **not** delete `talk.wav` / `talk.mp4`.
5. Verify: no remaining word-count ≤3 (after stage 1) and no remaining duration &lt;4s (after stage 2), except the single-clip edge case; spot-check a few merged durations with `ffprobe` (±0.05s of `end - start`).

When the user later says “merge shorts / merge under Ns / sync again”, re-run **only this step** (and bilingual/index refresh) on the named folders—do not re-ASR unless alignment is broken.

### 6. Deliver
- Attach or point to: both docs (md and/or docx), `sentences_by_sentence/` (and a zip if useful), and `index.md`.
- Report: talk folder path, **final** sentence count (after merge), English word count / Chinese character count, how many merge groups ran, any weak clips (open applause, truncated ending, ~20s+ compounds).
- Optional one-liner: pause-cut ≈ breath rhythm; sentence-cut ≈ grammar units; post-merge ≈ study-sized clips—sentence-cut + merge is the default.

## Tuning
- Long compound sentences (>~20s): keep as one clip for fidelity; offer a comma/clause re-split only if the user asks for easier shadowing.
- Low memory: process in stages; avoid loading two large Whisper models at once.
- Noisy video: denoise lightly or raise ASR beam; still cut on transcript sentences, not silence.
- GitHub sync (when asked): upload docs + `sentences_by_sentence/` only; keep large source media out of the repo unless the user insists.

## Success
Talk folder contains both documents and numbered sentence mp3s with a matching index; shorts have been merged by the default rules (or the user’s named thresholds); user knows the paths; pause-based cuts were not used as the primary deliverable.
