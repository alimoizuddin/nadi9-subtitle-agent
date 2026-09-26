"""Load an evidence pack. Only files named in manifest.json are read; nothing outside the pack root."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .util import read_json


@dataclass
class Pack:
    root: Path
    manifest: dict
    examples: list[dict]
    grammar_text: str
    dict_a: list[dict]
    dict_b: list[dict]
    experts: list[dict]
    feedback: list[dict]
    interviews: list[dict]
    episode: dict
    files_read: list[str] = field(default_factory=list)

    @property
    def characters(self) -> dict[str, dict]:
        return {c["id"]: c for c in self.episode["characters"]}


def _inside(root: Path, rel: str) -> Path:
    p = (root / rel).resolve()
    if root.resolve() not in p.parents and p != root.resolve():
        raise ValueError(f"manifest path escapes pack root: {rel}")
    if any(part.startswith("_") for part in Path(rel).parts):
        raise ValueError(f"refusing private path in manifest: {rel}")
    return p


def load_pack(root: str | Path) -> Pack:
    root = Path(root)
    manifest = read_json(root / "manifest.json")
    files_read = ["manifest.json"]
    by_type = {s["type"]: s for s in manifest["sources"]}

    def load(kind):
        rel = by_type[kind]["file"]
        files_read.append(rel)
        return _inside(root, rel)

    examples = read_json(load("approved_examples"))["examples"]
    grammar_text = load("grammar_note").read_text(encoding="utf-8")
    dicts = [s for s in manifest["sources"] if s["type"] == "dictionary"]
    dict_by_id = {}
    for s in dicts:
        files_read.append(s["file"])
        dict_by_id[s["id"]] = read_json(_inside(root, s["file"]))["entries"]
    experts = read_json(load("expert_notes"))["notes"]
    feedback = read_json(load("viewer_feedback"))["comments"]
    episode = read_json(load("episode"))

    interviews = []
    idir_rel = by_type["interviews"]["dir"]
    idir = _inside(root, idir_rel)
    for f in sorted(idir.glob("*.json")):
        files_read.append(f"{idir_rel}/{f.name}")
        interviews.append(read_json(f))

    return Pack(root=root, manifest=manifest, examples=examples, grammar_text=grammar_text,
                dict_a=dict_by_id.get("dictA", []), dict_b=dict_by_id.get("dictB", []),
                experts=experts, feedback=feedback, interviews=interviews, episode=episode,
                files_read=files_read)
