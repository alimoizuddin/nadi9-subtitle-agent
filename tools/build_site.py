"""Build the static results viewer published on GitHub Pages.

    python tools/build_site.py            # reads sample_run/, writes docs/index.html

The page is a single file with the run's data embedded, so it needs no server and no build step.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "sample_run"


def load():
    decisions = [json.loads(x) for x in (RUN / "subtitle_decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    rules = json.loads((RUN / "learned_rules.json").read_text(encoding="utf-8"))
    src = json.loads((RUN / "source_assessment.json").read_text(encoding="utf-8"))
    lex = json.loads((RUN / "lexicon.json").read_text(encoding="utf-8"))
    log = [json.loads(x) for x in (RUN / "run_log.jsonl").read_text(encoding="utf-8").splitlines()]
    poisoned = [{"term": t, "meaning": s["meaning"], "by": s.get("contradicted_by", [])}
                for t, c in lex.items() for s in c["senses"] if s["status"] == "POISON_SUSPECT"]
    calls = sum(1 for r in log if r["kind"] in ("MODEL_CALL", "MODEL_UNAVAILABLE"))  # every attempt counts against the budget
    return {
        "decisions": [{k: d[k] for k in ("subtitle_id", "start", "end", "speaker", "addressee", "relation",
                                          "source_text", "nadi_9_text", "gloss", "confidence", "confidence_reason",
                                          "decision", "evidence", "assumptions", "conflicts", "review_question",
                                          "checks", "model_self_confidence")} for d in decisions],
        "rules": [{k: r.get(k) for k in ("id", "kind", "statement", "status", "support", "counter", "dissent")}
                  for r in rules["rules"]] +
                 [{"id": r["id"], "kind": r["kind"], "statement": r.get("statement", ""), "status": r["status"],
                   "support": r["support"], "counter": [], "dissent": []} for r in rules["rejected_model_rules"]],
        "suspects": rules["suspect_examples"],
        "retracted": rules["retracted_examples"],
        "agreement": {k: src["sources"][k]["agreement"] for k in ("dictA", "dictB")},
        "poisoned": poisoned,
        "security": [{"source": s["source"], "ref": s["ref"], "excerpt": s["excerpt"]} for s in src["security_events"]],
        "model_calls": calls,
    }


def main():
    data = load()
    html = TEMPLATE.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False))
    out = ROOT / "docs" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)} ({len(html):,} bytes, {len(data['decisions'])} lines)")


TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nadi-9 Subtitle Review</title>
<meta name="description" content="Every subtitle decision made by the Nadi-9 agent, with the evidence behind it.">
<style>
:root{--bg:#f7f8fa;--card:#fff;--ink:#1a1c1f;--soft:#5b616b;--line:#e3e6ea;--accent:#2457c5;
--ok:#1f7a3a;--okbg:#e8f5ec;--rev:#9a5b00;--revbg:#fdf3e3;--no:#b3261e;--nobg:#fbeceb;--chip:#eef1f5}
@media (prefers-color-scheme:dark){:root{--bg:#111316;--card:#1a1d21;--ink:#e8eaed;--soft:#9aa0a8;--line:#2b2f35;
--accent:#7aa2ff;--ok:#6cc98a;--okbg:#17291e;--rev:#e9b35a;--revbg:#2d2413;--no:#f08a82;--nobg:#2e1a19;--chip:#23272d}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:980px;margin:0 auto;padding:28px 16px 60px}
h1{font-size:26px;margin:0 0 4px}
h2{font-size:18px;margin:34px 0 10px}
p{margin:6px 0}
.sub{color:var(--soft)}
a{color:var(--accent)}
.idea{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:8px;padding:12px 14px;margin:16px 0}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin:16px 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px}
.stat b{display:block;font-size:24px}
.stat span{color:var(--soft);font-size:13px}
.filters{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 14px}
.filters button{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:999px;padding:6px 12px;cursor:pointer;font:inherit;font-size:14px}
.filters button[aria-pressed=true]{background:var(--accent);border-color:var(--accent);color:#fff}
.line{background:var(--card);border:1px solid var(--line);border-radius:8px;margin:8px 0;overflow:hidden}
.line summary{list-style:none;cursor:pointer;padding:12px 14px;display:grid;grid-template-columns:56px 1fr auto;gap:12px;align-items:center}
.line summary::-webkit-details-marker{display:none}
.id{font-weight:700;color:var(--soft);font-size:13px}
.src{font-size:15px}
.nadi{font-family:ui-monospace,Consolas,monospace;font-size:14px;color:var(--accent)}
.nadi.none{color:var(--soft);font-family:inherit;font-style:italic}
.who{color:var(--soft);font-size:12.5px}
.badge{font-size:12px;font-weight:700;border-radius:999px;padding:3px 9px;white-space:nowrap}
.ACCEPT{background:var(--okbg);color:var(--ok)}
.HUMAN_REVIEW{background:var(--revbg);color:var(--rev)}
.INSUFFICIENT_EVIDENCE{background:var(--nobg);color:var(--no)}
.body{padding:0 14px 14px 82px;border-top:1px solid var(--line)}
.body h4{margin:12px 0 4px;font-size:13px;color:var(--soft);text-transform:uppercase;letter-spacing:.03em}
.bar{height:8px;background:var(--chip);border-radius:4px;overflow:hidden;max-width:260px}
.bar i{display:block;height:100%;background:var(--accent)}
.q{background:var(--revbg);border-radius:6px;padding:8px 10px}
.chips{display:flex;flex-wrap:wrap;gap:5px}
.chips span{background:var(--chip);border-radius:5px;padding:1px 7px;font-size:12.5px;font-family:ui-monospace,Consolas,monospace}
ul{margin:4px 0;padding-left:20px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:8px;overflow:hidden;font-size:14px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:12.5px;color:var(--soft);font-weight:600}
.st{font-size:12px;font-weight:700}
footer{margin-top:40px;color:var(--soft);font-size:13px}
@media (max-width:640px){.line summary{grid-template-columns:44px 1fr}.line summary .badge{grid-column:2;justify-self:start}.body{padding-left:14px}}
</style>
</head>
<body>
<main>
<h1>Nadi-9 Subtitle Review</h1>
<p class="sub">Every decision the agent made on an 18-line episode in a dialect no model has seen, and the evidence behind each one.</p>
<div class="idea"><b>The idea:</b> the model <i>proposes</i> rules and subtitles; separate, deterministic code <i>checks</i> every word against the evidence; and when the evidence runs out, the line goes to a human expert with one precise question instead of a confident guess.</div>
<div class="stats" id="stats"></div>

<h2>Subtitle decisions</h2>
<div class="filters" id="filters"></div>
<div id="lines"></div>

<h2>What the agent learned</h2>
<p class="sub">Grammar hypotheses, each tested against the approved examples. A model-proposed rule with no support is rejected.</p>
<table id="rules"><thead><tr><th>Rule</th><th>Statement</th><th>Status</th><th>Support</th><th>Against</th></tr></thead><tbody></tbody></table>

<h2>Traps it caught</h2>
<ul id="traps"></ul>

<footer>
Evidence pack is <b>synthetic</b>: the official pack was not received, so a labelled practice pack was used.
Built with Claude Code under Ali Moizuddin's direction. Source and full audit trail:
<a href="https://github.com/alimoizuddin/nadi9-subtitle-agent">github.com/alimoizuddin/nadi9-subtitle-agent</a>
</footer>
</main>
<script>
const D = /*__DATA__*/null;
const LABEL = {ACCEPT:"Accepted", HUMAN_REVIEW:"Needs expert", INSUFFICIENT_EVIDENCE:"No evidence"};
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const count = k => D.decisions.filter(d => d.decision === k).length;

document.getElementById("stats").innerHTML = [
  [D.decisions.length, "subtitle lines"],
  [count("ACCEPT"), "accepted"],
  [count("HUMAN_REVIEW"), "sent to an expert"],
  [count("INSUFFICIENT_EVIDENCE"), "refused: no evidence"],
  [`${D.model_calls} / 25`, "model calls used"],
  [`${Math.round(D.agreement.dictA*100)}% · ${Math.round(D.agreement.dictB*100)}%`, "Dictionary A · B agreement"],
].map(([b, s]) => `<div class="stat"><b>${esc(b)}</b><span>${esc(s)}</span></div>`).join("");

let filter = "ALL";
function renderFilters(){
  const opts = [["ALL","All 18"],["ACCEPT",`Accepted (${count("ACCEPT")})`],["HUMAN_REVIEW",`Needs expert (${count("HUMAN_REVIEW")})`],["INSUFFICIENT_EVIDENCE",`No evidence (${count("INSUFFICIENT_EVIDENCE")})`]];
  const box = document.getElementById("filters");
  box.innerHTML = opts.map(([k,l]) => `<button data-k="${k}" aria-pressed="${k===filter}">${esc(l)}</button>`).join("");
  box.querySelectorAll("button").forEach(b => b.onclick = () => { filter = b.dataset.k; renderFilters(); renderLines(); });
}
function renderLines(){
  document.getElementById("lines").innerHTML = D.decisions.filter(d => filter==="ALL" || d.decision===filter).map(d => `
  <details class="line">
    <summary>
      <span class="id">${esc(d.subtitle_id)}</span>
      <span>
        <div class="src">${esc(d.source_text)}</div>
        <div class="nadi ${d.nadi_9_text ? "" : "none"}">${d.nadi_9_text ? esc(d.nadi_9_text) : "withheld: evidence insufficient"}</div>
        <div class="who">${esc(d.speaker)} → ${esc(d.addressee)} (${esc(d.relation)}) · ${esc(d.start)}</div>
      </span>
      <span class="badge ${d.decision}">${LABEL[d.decision]}</span>
    </summary>
    <div class="body">
      <h4>Confidence ${d.confidence.toFixed(2)}</h4>
      <div class="bar"><i style="width:${Math.round(d.confidence*100)}%"></i></div>
      <p>${esc(d.confidence_reason)}</p>
      ${d.review_question ? `<h4>Question for the expert</h4><div class="q">${esc(d.review_question)}</div>` : ""}
      ${d.gloss.length ? `<h4>Word by word</h4><div class="chips">${d.gloss.map(g => `<span>${esc(g)}</span>`).join("")}</div>` : ""}
      ${d.checks.length ? `<h4>Checker findings</h4><ul>${d.checks.map(c => `<li><b>${esc(c.status)}</b> ${esc(c.check)}: ${esc(c.detail)}</li>`).join("")}</ul>` : ""}
      ${d.conflicts.length ? `<h4>Conflicting evidence</h4><ul>${d.conflicts.map(c => `<li>${esc(c)}</li>`).join("")}</ul>` : ""}
      ${d.assumptions.length ? `<h4>Assumptions</h4><ul>${d.assumptions.map(a => `<li>${esc(a)}</li>`).join("")}</ul>` : ""}
      ${d.evidence.length ? `<h4>Evidence</h4><div class="chips">${d.evidence.map(e => `<span>${esc(e)}</span>`).join("")}</div>` : ""}
      ${d.model_self_confidence != null ? `<p class="sub">Drafting model rated itself ${d.model_self_confidence}; recorded, never used.</p>` : ""}
    </div>
  </details>`).join("");
}
document.querySelector("#rules tbody").innerHTML = D.rules.map(r => `<tr>
  <td><b>${esc(r.id)}</b></td><td>${esc(r.statement)}</td>
  <td class="st">${esc(r.status.replaceAll("_"," ").toLowerCase())}</td>
  <td>${(r.support||[]).length}</td><td>${esc([...(r.counter||[]), ...(r.dissent||[])].join(", ")) || "–"}</td></tr>`).join("");
document.getElementById("traps").innerHTML = [
  ...D.poisoned.map(p => `Poisoned dictionary entry: <b>${esc(p.term)}</b> = "${esc(p.meaning)}", contradicted by ${esc(p.by.join(", "))}`),
  ...Object.entries(D.suspects).map(([e, rs]) => `Approved example <b>${esc(e)}</b> doubted: it breaks ${esc(rs.join(", "))}`),
  ...D.retracted.map(e => `Example <b>${esc(e)}</b> retracted mid-run; already excluded, 0 lines changed`),
  ...D.security.map(s => `Prompt injection quarantined in <b>${esc(s.source)} ${esc(s.ref)}</b>: "${esc(s.excerpt)}…"`),
].map(x => `<li>${x}</li>`).join("");
renderFilters(); renderLines();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
