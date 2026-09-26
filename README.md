# Nadi-9 subtitle agent

An agent that learns a dialect it has never seen from a small, contradictory evidence pack, drafts
subtitles, and **refuses to pretend**. Every line comes back as `ACCEPT`, `HUMAN_REVIEW` or
`INSUFFICIENT_EVIDENCE`, with its evidence, its assumptions, the conflicts that could change it and
one precise question for a language expert.

> **The evidence pack in `pack/` is synthetic.** STAGE's official pack had not arrived when this was
> built (requested 25 Sep 2026). The synthetic pack copies the difficulty the brief describes:
> poisoned dictionary entries, two wrong approved examples, disagreeing experts, an audio-only
> interview, prompt injections, and a status-sensitive word. See [`pack/PACK_NOTICE.md`](pack/PACK_NOTICE.md).
> The agent code does not depend on it: an adapter for the real pack's format is the only change needed.

## Run it (no API key needed)

```bash
python run.py run --pack pack --out sample_run --events events/demo_events.json
```

Python 3.10+, standard library only. Output:

```
18 lines: {'ACCEPT': 5, 'INSUFFICIENT_EVIDENCE': 4, 'HUMAN_REVIEW': 9}
DO NOT RELEASE YET: 13 of 18 lines need a Nadi-9 expert. Send review_queue.json; 5 lines are ready.
model calls 7/25, tool calls 26/50
```

Tests and the trap scorer:

```bash
pip install pytest
python -m pytest -q
python eval/score.py sample_run
```

## What you get in `sample_run/`

| File | What it is |
|---|---|
| `final_report.md` | **Start here.** Release recommendation, every line, the expert questions, what was learned, every surprise event and what it changed. |
| `subtitles.srt` | The subtitle proposal. Accepted lines plain, `[?]` = needs review, `[NO EVIDENCE]` = withheld (source shown). |
| `subtitle_decisions.jsonl` | One decision per line: text, gloss, confidence + reason, evidence ids, assumptions, conflicts, review question, failed checks, knowledge version. |
| `review_queue.json` | What to send the linguist, most important first. |
| `learned_rules.json` | Every grammar hypothesis with its support, counterexamples, dissent and status, plus rejected model rules and suspect examples. |
| `lexicon.json` | Every word, every candidate meaning, which sources back each one, and why a meaning was rejected. |
| `source_assessment.json` | Measured trust per source, precedence policy, quarantined injections. |
| `run_log.jsonl` / `revisions.json` | Full audit trail: every model/tool call, event, re-plan and superseded decision. |

## Modes

| `--provider` | Needs | Use |
|---|---|---|
| `replay` (default) | nothing | Evaluators. Answers come from `replay/*.json`. |
| `anthropic` | `pip install anthropic`, `ANTHROPIC_API_KEY` | Live run; answers are recorded to `replay/`. |
| `claude-cli` | Claude Code logged in | Live run through `claude -p`; recorded the same way. |

`--record-missing` makes replay mode write any prompt it has no answer for to `replay/pending/`, so a
model (or a person) can answer offline and the run can be repeated; `tools/answer.py` stores the
answer with the prompt's hash. That is how the sample run's answers were produced (see
[`AI_COLLABORATION.md`](AI_COLLABORATION.md)).

Budget: `--max-model-calls 25 --max-tool-calls 50` (the brief's limits are the defaults). When a
budget runs out the remaining lines abstain rather than guess.

## Surprise events

`events/demo_events.json` fires four events mid-run: a model-proposed grammar rule with no support,
a model outage, a linguist correction halfway through, and a retraction of an approved example.
The injected text in Dictionary A and in viewer feedback, the poisoned entries and the failed
transcription are part of the pack itself. Write your own event file in the same format to test others.

## Layout

```
src/nadi9/      pipeline.py (agent loop) · verify.py (independent checker) · decide.py
                lexicon.py · rules.py · sources.py · guard.py · morph.py · prompts.py · llm.py · report.py
pack/           synthetic evidence pack
events/         surprise events for the sample run
replay/         recorded model answers (with prompt hashes)
eval/           answer key + scorer (never read by the agent)
tests/          pytest suite
sample_run/     outputs of the command above
```

[`ARCHITECTURE.md`](ARCHITECTURE.md) explains the design · [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md)
lists what is incomplete and which decisions must stay with humans.
