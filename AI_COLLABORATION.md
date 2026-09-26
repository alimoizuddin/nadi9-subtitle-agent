# AI collaboration log

I built this with AI assistants in two roles, and kept those roles separate, the same way the agent
keeps its proposer and its verifier separate.

| Tool | Role | What it did |
|---|---|---|
| Claude Code (Claude Opus 5.5) | Main pair-programmer | Designed the synthetic pack and its traps with me; wrote `src/`; ran every change against the pack and read the outputs |
| Claude, answering offline prompts | The agent's **drafting model** in the sample run | Answered the 7 prompts the pipeline emitted (`replay/*.json`) |
| Claude Omni (Claude Code over an OmniRoute gateway) | Worker, tried and dropped | Given a written brief for the test suite; see row 7 below |

## How the sample run's model answers were produced

No Anthropic API key was available and `claude -p` could not run nested inside the Claude Code
session, so I added a file-based loop instead of faking a live call:

1. `python run.py run ... --record-missing` writes each prompt the pipeline needs to
   `replay/pending/<key>.prompt.txt` and continues safely (those lines abstain).
2. Claude answered each prompt file as the drafting model, from the prompt alone.
3. `tools/answer.py` stored the answer with the SHA-256 of the exact prompt.
4. The run is repeated; later prompts depend on earlier answers, so this went round five times.

The recorded answers are therefore real model output for the real prompts, not hand-edited
fixtures. The surprise events in `events/demo_events.json` (the fake plural rule, the outage) are
labelled injections, not presented as something the model did on its own. The live providers
(`--provider anthropic|claude-cli`) record in the same format.

## What the AI got wrong, and how it was caught

| # | What it suggested or did | How it was caught | What I did |
|---|---|---|---|
| 1 | Linked interview and expert evidence to a meaning by **word overlap**. "younger brother" (Dictionary A's poisoned entry for *anno*) picked up support from an interview line about an "elder brother", so *anno* came out CONTESTED instead of POISONED. | Compared the first lexicon dump with the traps the pack was designed to contain | Evidence now has to contain a **whole meaning phrase** (`_phrase_in` in `lexicon.py`) |
| 2 | Filtered out meaning phrases shorter than 3 characters. That silently dropped "be", so *si* ("be/was") lost its interview support and became WEAK. | Read the translation prompt the pipeline actually sent, before answering it | Filter lowered to 2 characters |
| 3 | Re-checked every line after **any** rule status change. Retracting E15 re-checked 10 of 18 lines, though no check outcome could change. | The re-plan log showed 10 affected lines for an example already excluded | Only a change that crosses a trust boundary triggers re-checks; the run now reports `RETRACTION_ALREADY_HANDLED` and 0 affected |
| 4 | When a redraft failed during an outage, the placeholder **overwrote the previous valid draft**. | Walked through the outage path by hand while reviewing `_draft` | Outages keep the earlier proposal |
| 5 | Ordered expert questions so a missing "even" came before the checker's rejection of the whole draft. | Read the review queue as a linguist would | Checker failures now come before partial gaps |
| 6 | **As the drafting model**, rendered "call on the phone" as *phone se boliriji* ("spoke by phone"), a plausible paraphrase from interview I2. | The independent verifier rejected it: *boli* is only attested as say/tell/speak | The repair moved "call" to a gap and gave the paraphrase to the reviewer as a candidate instead of shipping it |
| 7 | **Claude Omni**, briefed to write the required tests, started with an unrequested `test_util.py`. 3 of its 11 tests failed on its own wrong expectations (it expected `lemma("tried") == "tri"`). | Ran its file before accepting anything | Stopped the worker, deleted the file, and wrote the suite in the main session against the brief |
| 8 | The exact-match score in `eval/score.py` (13/13 drafts match the key) looked like a quality metric. | It is circular: I wrote both the key and the drafts | Labelled in the scorer output as "not a quality score" |

## What I did not accept

- **Letting the model's confidence count.** The drafting model rated itself ≥ 0.80 on S006 and S015.
  Both depend on a loanword rule an expert disputes for rural speech. Self-ratings are recorded and
  reported, never used; a test enforces it.
- **Filling gaps with fluent guesses.** For "welcome home", "every", "already" and the idiom in S009,
  the assistant could produce a plausible Nadi-9 sentence from the lexicon. Each one would be an
  invention, so those lines abstain and put the candidate wording in `assumptions` for the linguist.
- **Treating the biggest dictionary as the default.** Dictionary A covers the most words; its weight
  comes from measured agreement (85%), not size.

## How AI output was checked

- Every change was run end to end against the pack, and `eval/score.py` checks all 13 planted traps
  after each run.
- 33 tests in `tests/` cover the four behaviours the brief names (conflict, unsupported term,
  correction event, tool failure) plus poisoning, injections, respect, budget, determinism and
  replay drift. They run in about 1.5 seconds.
- Every model claim the pipeline relies on is re-checked in code: rule quotes are matched verbatim,
  rules are tested against examples, drafts go through `verify.py`.
