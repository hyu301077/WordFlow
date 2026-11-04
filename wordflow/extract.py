"""英文文本清洗和词汇提取。"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

_CODE_FENCE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`\n]+`")
_HTML = re.compile(r"<[^>]+>")
_URL = re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_WIN_PATH = re.compile(r"\b[A-Za-z]:\\[^\s]+")
_UNIX_PATH = re.compile(r"(?:(?:\./|\.\./|/)[\w./\\-]+)")
_TOKEN = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)*")
_REPEAT = re.compile(r"(.)\1{3,}", re.IGNORECASE)

_NON_VOCAB = {
    "http",
    "https",
    "www",
    "com",
    "org",
    "net",
    "html",
    "htm",
    "php",
    "aspx",
    "pdf",
    "docx",
    "txt",
    "md",
    "json",
    "xml",
    "css",
    "js",
}

DEFAULT_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "else", "when", "while",
    "of", "to", "in", "on", "at", "by", "for", "with", "about", "against",
    "between", "into", "through", "during", "before", "after", "from", "up",
    "down", "out", "off", "over", "under", "again", "here", "there", "all",
    "any", "both", "each", "few", "more", "most", "other", "some", "such",
    "no", "nor", "not", "only", "own", "same", "so", "than", "too", "very",
    "can", "will", "just", "should", "now", "i", "me", "my", "we", "our",
    "you", "your", "he", "him", "his", "she", "her", "it", "its", "they",
    "them", "their", "what", "which", "who", "whom", "this", "that", "these",
    "those", "am", "is", "are", "was", "were", "be", "been", "being", "have",
    "has", "had", "having", "do", "does", "did", "doing", "as", "until",
    "because", "although", "though", "once", "how", "why", "where", "don",
    "don't", "isn't", "aren't", "wasn't", "weren't", "hasn't", "haven't",
    "hadn't", "doesn't", "don't", "didn't", "won't", "wouldn't", "couldn't",
    "shouldn't", "can't", "cannot", "i'm", "it's", "that's", "there's",
    "what's", "let's", "i've", "you've", "we're", "they're", "i'll", "you'll",
    "we'll", "they'll", "i'd", "you'd", "could", "would", "may", "might",
    "must", "shall", "ought", "vs", "etc", "via", "per", "onto", "upon",
    "within", "without", "across", "whether", "while", "of",
}


@dataclass
class ExtractOptions:
    filter_stopwords: bool = True
    filter_proper: bool = True
    filter_acronyms: bool = True
    stopwords_path: Path | None = None


@dataclass
class ExtractedWord:
    lemma: str
    frequency: int
    surfaces: dict[str, int] = field(default_factory=dict)
    example: str | None = None

    @property
    def display_surface(self) -> str:
        if not self.surfaces:
            return self.lemma
        return max(self.surfaces.items(), key=lambda item: (item[1], -len(item[0])))[0]


def load_stopwords(path: Path | None) -> set[str]:
    words = set(DEFAULT_STOPWORDS)
    if path and path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip().lower()
            if line and not line.startswith("#"):
                words.add(line)
    return words


def clean_text(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4 :]
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = _CODE_FENCE.sub(" ", text)
    text = _INLINE_CODE.sub(" ", text)
    text = _HTML.sub(" ", text)
    text = _MD_IMAGE.sub(" ", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _URL.sub(" ", text)
    text = _EMAIL.sub(" ", text)
    text = _WIN_PATH.sub(" ", text)
    text = _UNIX_PATH.sub(" ", text)
    text = re.sub(r"[#>*_~]+", " ", text)
    return text


def _sentence_start(text: str, index: int) -> bool:
    previous = text[:index]
    stripped = previous.rstrip()
    if not stripped:
        return True
    return stripped[-1] in ".!?\n"


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [part.strip() for part in parts if part.strip()]


def _pick_example(sentences: list[str], surface: str) -> str | None:
    pattern = re.compile(rf"\b{re.escape(surface)}\b", re.IGNORECASE)
    chosen = None
    for sentence in sentences:
        if not pattern.search(sentence):
            continue
        letters = sum(ch.isalpha() for ch in sentence)
        if letters < 8:
            continue
        if len(sentence) > 280:
            continue
        if chosen is None or 40 <= len(sentence) <= 180:
            chosen = sentence
            if 40 <= len(sentence) <= 180:
                break
    return chosen


def extract_words(text: str, options: ExtractOptions, lexicon) -> tuple[list[ExtractedWord], int]:
    cleaned = clean_text(text)
    stopwords = load_stopwords(options.stopwords_path) if options.filter_stopwords else set()
    raw_tokens = list(_TOKEN.finditer(cleaned))
    total_alpha = 0
    mid_caps = 0
    raw_total = 0
    prepared = []
    for match in raw_tokens:
        token = match.group(0)
        sentence_start = _sentence_start(cleaned, match.start())
        pieces = _expand_token(token, lexicon)
        for piece in pieces:
            if len(piece) >= 2 and piece.isalpha():
                raw_total += 1
            if piece.isalpha() and len(piece) > 1 and piece[0].isupper() and piece[1:].islower() and not sentence_start:
                mid_caps += 1
            if piece.isalpha():
                total_alpha += 1
            prepared.append((piece, sentence_start))
    title_case = total_alpha > 20 and mid_caps / max(total_alpha, 1) > 0.4

    grouped: dict[str, dict] = {}
    for piece, sentence_start in prepared:
        if not _keep_token(piece, options, stopwords):
            continue
        lower = piece.lower()
        bucket = grouped.get(lower)
        if bucket is None:
            bucket = {
                "lower": 0,
                "mid": 0,
                "start": 0,
                "surfaces": Counter(),
            }
            grouped[lower] = bucket
        bucket["surfaces"][piece] += 1
        if piece.isupper():
            bucket["mid"] += 1
        elif piece[0].isupper() and not sentence_start:
            bucket["mid"] += 1
        elif piece[0].isupper() and sentence_start:
            bucket["start"] += 1
        else:
            bucket["lower"] += 1

    counts: Counter[str] = Counter()
    surfaces: dict[str, Counter] = defaultdict(Counter)
    for lower, bucket in grouped.items():
        if _is_proper(lower, bucket, options, lexicon, title_case):
            continue
        lemma = lexicon.resolve_lemma(lower)
        if not lemma or len(lemma) > 40:
            continue
        if options.filter_stopwords and lemma in stopwords and lower in stopwords:
            continue
        counts[lemma] += sum(bucket["surfaces"].values())
        for surface, count in bucket["surfaces"].items():
            surfaces[lemma][surface] += count

    sentences = _sentences(cleaned)
    extracted = []
    for lemma, frequency in counts.items():
        surface = max(surfaces[lemma].items(), key=lambda item: item[1])[0]
        extracted.append(
            ExtractedWord(
                lemma=lemma.lower(),
                frequency=frequency,
                surfaces=dict(surfaces[lemma]),
                example=_pick_example(sentences, surface),
            )
        )
    extracted.sort(key=lambda item: (-item.frequency, item.lemma))
    return extracted, raw_total


def _expand_token(token: str, lexicon) -> list[str]:
    if "-" not in token:
        return [token]
    if lexicon.has_entry(token):
        return [token]
    return [part for part in token.split("-") if part]


def _keep_token(token: str, options: ExtractOptions, stopwords: set[str]) -> bool:
    if len(token) < 2 or len(token) > 40:
        return False
    if _REPEAT.search(token):
        return False
    lower = token.lower()
    if lower in _NON_VOCAB:
        return False
    if options.filter_stopwords and lower in stopwords:
        return False
    if options.filter_acronyms and token.isupper() and token.isalpha() and 2 <= len(token) <= 6:
        return False
    return True


def _is_proper(lower: str, bucket: dict, options: ExtractOptions, lexicon, title_case: bool) -> bool:
    if not options.filter_proper or title_case:
        return False
    if lexicon.is_common(lower):
        return False
    if bucket["lower"] > 0:
        return False
    if bucket["mid"] > 0:
        return True
    return not lexicon.has_entry(lower)
