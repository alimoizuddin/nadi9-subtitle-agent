# Known limitations

## Left incomplete on purpose

- **The official pack.** Built and tested against a synthetic pack because STAGE's had not arrived.
  The real pack needs a loader to the schema in `ARCHITECTURE.md` §2. Its grammar note is six pages of
  prose and its examples may not come glossed; glossing them would need a model step, checked the same way.
- **Audio.** There is a transcription tool interface, but no speech-to-text backend. In the synthetic
  pack it fails for the audio-only interview I3, and the run records what evidence was lost.
- **English analysis is small.** The verifier's lemmatiser and synonym table are a few dozen lines.
  They are enough for this episode and easy to inspect, but will mis-handle phrasal verbs, idioms and
  long sentences. This is the first thing to replace at scale.
- **One token, one meaning.** Alignment is token-to-source-words. Multi-word Nadi-9 expressions
  and discontinuous constructions are not modelled.
- **Word order is checked only where the grammar note is explicit** (verb-final, negation, question
  particle, postpositions). Adjective and indirect-object placement are undocumented, so drafts that
  use them are flagged through assumptions rather than checked.
- **Rule language is a fixed set of 11 kinds.** A hypothesis outside them is rejected as untestable
  rather than tested. That is safe, but it limits what the agent can learn.
- **Present tense and imperatives** rest on the grammar note's own uncertain remarks and one example.
- **Thresholds are judgement calls:** ≥2 examples to call a dictionary entry poisoned, ≥3 supporting
  examples to doubt an approved example, 0.80 to accept, 17 chars/sec. They are constants in the code,
  named and easy to change, but not tuned on real data.
- **No user interface.** The brief asks for the decision pipeline first; review happens in
  `review_queue.json` and `final_report.md`.
- **Sample model answers came from one model answering offline** (see `AI_COLLABORATION.md`). A live
  run with a different model will produce different drafts. The verifier and decisions still apply.

## Decisions that must stay with humans

1. **Whether a line ships.** The agent recommends; a Nadi-9 speaker approves. Even ACCEPT lines
   should be spot-checked before release.
2. **Whether a status-sensitive word stays** (S012: *keth* said to an elder). That is a creative and
   cultural call about intent, not a lookup. The experts themselves disagree.
3. **Which variety the show speaks.** Rural `-u` loans vs unchanged loans (S006, S015) is a
   production decision about the characters, not a fact in the evidence.
4. **Accepting a correction.** Corrections are applied and logged, but who may correct the lexicon
   (and how two corrections that disagree are resolved) is a governance decision.
5. **Idioms and humour** (S009, S014). Whether to keep a literal image or find a native one needs a
   speaker with taste, not a dictionary.
6. **Retiring a source.** The agent down-weights Dictionary A by measurement; deciding never to use
   a vendor's material again is a human call.
