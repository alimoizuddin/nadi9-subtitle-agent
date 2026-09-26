"""Small shared helpers: JSON IO, timecodes, and the tiny English normaliser the verifier uses."""
from __future__ import annotations

import json
import re
from pathlib import Path

# --- IO -----------------------------------------------------------------------------------

def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=_default) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=_default) + "\n")


def _default(o):
    if isinstance(o, set):
        return sorted(o)
    raise TypeError(f"not serialisable: {type(o)}")


def extract_json(text: str):
    """Model replies sometimes wrap JSON in prose or code fences. Take the outermost object."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in model reply")
    return json.loads(text[start:end + 1])


# --- timecodes ----------------------------------------------------------------------------

def tc_to_seconds(tc: str) -> float:
    h, m, s = tc.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def seconds_to_srt(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# --- English normalisation (deliberately small and inspectable) -------------------------------

IRREGULAR = {
    "came": "come", "went": "go", "gave": "give", "ate": "eat", "saw": "see", "heard": "hear",
    "forgot": "forget", "did": "do", "does": "do", "was": "be", "is": "be", "are": "be",
    "were": "be", "am": "be", "said": "say", "says": "say", "brought": "bring", "took": "take",
    "me": "i", "us": "we", "him": "he", "her": "she", "your": "you", "my": "i", "his": "he",
    "children": "child", "left": "leave",
}

# Words the verifier does not require a Nadi-9 token for. Negation, tense and questions are
# checked separately by the grammar checks, not by coverage.
FUNCTION_WORDS = {
    "the", "a", "an", "to", "of", "in", "on", "at", "for", "and", "be", "do", "will", "shall",
    "not", "n't", "no", "'ll", "let",
}

NEGATORS = {"not", "n't", "never", "no"}


def tokenize_en(text: str) -> list[str]:
    text = text.replace("’", "'").lower()
    text = re.sub(r"n't\b", " n't", text)
    return re.findall(r"[a-z]+'?[a-z]*|n't|\d+", text)


def lemma(word: str) -> str:
    w = word.lower().strip()
    if w in IRREGULAR:
        return IRREGULAR[w]
    if w.isdigit() or len(w) <= 3:
        return w
    if w.endswith("ing") and len(w) > 5:
        return w[:-3]
    if w.endswith("ied"):
        return w[:-3] + "y"
    if w.endswith("ed") and not w.endswith("eed"):
        return w[:-2]
    if w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def content_lemmas(text: str) -> list[str]:
    return [lemma(w) for w in tokenize_en(text) if w not in FUNCTION_WORDS and lemma(w) not in FUNCTION_WORDS]


def meaning_phrases(meaning: str) -> set[str]:
    """'return, come back (to a place)' -> {'return', 'come back'}; each phrase lemmatised."""
    m = re.sub(r"\([^)]*\)", "", meaning.lower())
    out = set()
    for part in re.split(r"[,;/]", m):
        words = [lemma(w) for w in tokenize_en(part)]
        words = [w for w in words if w not in {"the", "a", "an"}]
        if words:
            out.add(" ".join(words))
    return {SYNONYMS.get(p, p) for p in out}


# Grammatical glosses written differently by different sources.
SYNONYMS = {
    "question marker": "question particle",
    "negation": "not",
    "neg": "not",
    "q": "question particle",
}


def meaning_words(meaning: str) -> set[str]:
    words = set()
    for p in meaning_phrases(meaning):
        words.update(p.split())
    return words
