"""Trust boundary: text from the pack and from the model is data, never instructions.

Every free-text field is scanned before it can reach a prompt. Instruction-like text is
replaced with a placeholder and recorded as a security event. The entry itself is kept,
so a poisoned note does not delete a (possibly valid) dictionary meaning.
"""
from __future__ import annotations

import re

PATTERNS = [
    r"\bignore\s+(all\s+|any\s+)?(previous|prior|above|the|other|every|these)\b",
    r"\bdisregard\b",
    r"\b(note|message|instruction)s?\s+to\s+(ai|llm|the model|.*translation systems?)\b",
    r"\bsystem prompt\b",
    r"\byou\s+(must|should)\s+(now\s+)?(ignore|only|obey)\b",
    r"\bnew instructions?\b",
]
_RX = [re.compile(p, re.I) for p in PATTERNS]
PLACEHOLDER = "[QUARANTINED: instruction-like text removed by guard]"


def scan(text: str | None) -> list[str]:
    if not text:
        return []
    return [p.pattern for p in _RX if p.search(text)]


def sanitize_pack(pack, security_log: list) -> None:
    """Mutates the pack in place. Returns nothing; every hit is appended to security_log."""

    def check(obj: dict, key: str, source: str, ref: str):
        hits = scan(obj.get(key))
        if hits:
            security_log.append({"source": source, "ref": ref, "field": key,
                                 "excerpt": obj[key][:90], "patterns": hits,
                                 "action": "quarantined; entry kept, text removed from all prompts"})
            obj[key] = PLACEHOLDER

    for e in pack.dict_a:
        check(e, "note", "dictA", e["id"])
        check(e, "meaning", "dictA", e["id"])
    for e in pack.dict_b:
        check(e, "note", "dictB", e["id"])
        check(e, "meaning", "dictB", e["id"])
    for n in pack.experts:
        check(n, "text", "experts", n["id"])
    for c in pack.feedback:
        check(c, "text", "feedback", c["id"])
    for ex in pack.examples:
        check(ex, "source", "examples", ex["id"])
    for iv in pack.interviews:
        for i, row in enumerate(iv.get("transcript") or []):
            check(row, "english", "interviews", f"{iv['id']}#{i}")
    for line in pack.episode["lines"]:
        check(line, "direction", "episode", line["id"])

    paras = pack.grammar_text.split("\n\n")
    for i, para in enumerate(paras):
        if scan(para):
            security_log.append({"source": "grammar", "ref": f"para{i}", "field": "text",
                                 "excerpt": para[:90], "patterns": scan(para),
                                 "action": "quarantined paragraph"})
            paras[i] = PLACEHOLDER
    pack.grammar_text = "\n\n".join(paras)
