"""Morphological analysis of a Nadi-9 token against the current lexicon and suffix hypotheses.

The suffix table is not hard-coded: it is whatever the rule hypotheses currently say, so a
rejected hypothesis (e.g. a plural '-lu' the model invented) cannot be used to parse a word.
"""
from __future__ import annotations

import re

# Order matters: outermost suffix first. -ji follows tense (G-RESPECT-2).
OUTER = ("RESP",)
INNER = ("PAST", "FUT", "HORT")
NOMINAL = ("POSS",)


def clean(token: str) -> str:
    return re.sub(r"[^\w-]", "", token.lower())


def gloss_parts(gloss: str) -> tuple[str, list[str]]:
    """'return-PAST-RESP' -> ('return', ['PAST','RESP']); 'you.RESP' -> ('you', ['RESP']);
    'elder.brother' -> ('elder brother', [])."""
    head, *rest = gloss.split("-")
    feats = [r for r in rest]
    bits = head.split(".")
    words = [b for b in bits if not b.isupper()]
    feats = [b for b in bits if b.isupper()] + feats
    lemma = " ".join(words) if words else head
    return lemma, feats


def analyse(token: str, terms: set[str], suffix_table: dict[str, str]) -> dict:
    """Returns {token, root, feats, suffixes, unknown_suffix, kind}."""
    t = clean(token)
    if t.isdigit():
        return {"token": t, "root": t, "feats": [], "suffixes": [], "unknown_suffix": None, "kind": "number"}
    if t in terms:
        return {"token": t, "root": t, "feats": [], "suffixes": [], "unknown_suffix": None, "kind": "word"}

    by_feat = {}
    for suf, feat in suffix_table.items():
        by_feat.setdefault(feat, []).append(suf)

    def strip(word, feats_allowed):
        for feat in feats_allowed:
            for suf in by_feat.get(feat, []):
                if word.endswith(suf) and len(word) > len(suf):
                    return word[: -len(suf)], suf, feat
        return None

    word, sufs, feats = t, [], []
    got = strip(word, OUTER)
    if got:
        word, s, f = got
        sufs.insert(0, s)
        feats.insert(0, f)
    got = strip(word, INNER)
    if got:
        word, s, f = got
        sufs.insert(0, s)
        feats.insert(0, f)
    if word in terms and sufs:
        return {"token": t, "root": word, "feats": feats, "suffixes": sufs, "unknown_suffix": None, "kind": "word"}

    got = strip(t, NOMINAL)
    if got and got[0] in terms:
        return {"token": t, "root": got[0], "feats": [got[2]], "suffixes": [got[1]], "unknown_suffix": None, "kind": "word"}

    # Known root followed by something we cannot parse -> report the leftover explicitly.
    best = max((x for x in terms if t.startswith(x) and len(x) >= 2), key=len, default=None)
    if best:
        return {"token": t, "root": best, "feats": [], "suffixes": [], "unknown_suffix": t[len(best):], "kind": "word"}
    return {"token": t, "root": None, "feats": [], "suffixes": [], "unknown_suffix": None, "kind": "unknown"}
