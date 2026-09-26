"""The checker catches each kind of error on its own, with no model involved."""
from conftest import REPLAY, line, run_agent, tok

from nadi9 import verify
from nadi9.llm import ReplayProvider

S001 = [tok("anno", ["elder", "brother"]), tok("tuvan", ["you"]), tok("veluriji", ["came", "back"]), tok("ka", ["?"])]


def kinds(agent, lid, text, tokens, fails_only=True, source=None, **extra):
    ln = dict(line(agent, lid))
    if source:
        ln["text"] = source
    prop = {"nadi_9_text": text, "tokens": tokens, **extra}
    res = verify.verify(ln, agent.chars, prop, agent.lex, agent.rules, agent.cfg)
    return {c["kind"] for c in (res.fails if fails_only else res.checks)}


def test_correct_line_passes(learned):
    assert kinds(learned, "S001", "anno, tuvan veluriji ka", S001) == set()


def test_familiar_pronoun_to_elder(learned):
    t = [S001[0], tok("tu", ["you"]), S001[2], S001[3]]
    assert "RESPECT" in kinds(learned, "S001", "anno, tu veluriji ka", t)


def test_missing_respect_suffix(learned):
    t = [S001[0], S001[1], tok("veluri", ["came", "back"]), S001[3]]
    assert "RESPECT" in kinds(learned, "S001", "anno, tuvan veluri ka", t)


def test_negation_after_verb(learned):
    t = [tok("ma", ["I"]), tok("city", ["city"]), tok("ke", ["to"]), tok("velusa", ["go", "back"]), tok("mo", ["not"])]
    assert "GRAMMAR" in kinds(learned, "S015", "ma city ke velusa mo", t)


def test_missing_question_particle(learned):
    assert "GRAMMAR" in kinds(learned, "S001", "anno, tuvan veluriji", S001[:3])


def test_wrong_tense(learned):
    t = [S001[0], S001[1], tok("velusaji", ["came", "back"]), S001[3]]
    assert "GRAMMAR" in kinds(learned, "S001", "anno, tuvan velusaji ka", t)


def test_changed_number(learned):
    t = [tok("ma", ["I"]), tok("4", ["3"]), tok("sanu", ["years"]), tok("pisu", ["after"]), tok("veluri", ["came", "back"])]
    assert "NUMBERS" in kinds(learned, "S002", "ma 4 sanu pisu veluri", t)


def test_omission(learned):
    t = [tok("ma", ["I"]), tok("3", ["3"]), tok("veluri", ["came", "back"])]
    assert "OMISSION" in kinds(learned, "S002", "ma 3 veluri", t)


def test_addition(learned):
    t = S001[:3] + [tok("kalu", ["tomorrow"]), S001[3]]
    assert "ADDITION" in kinds(learned, "S001", "anno, tuvan veluriji kalu ka", t)


def test_poisoned_meaning_use(learned):
    t = [tok("vo", ["she"]), tok("hesuri", ["cried"])]
    assert "POISON_USE" in kinds(learned, "S017", "vo hesuri", t, source="She cried.")


def test_short_line_timing(learned):
    t = [tok("ma", ["I"]), tok("vo", ["him"]), tok("40", ["40"]), tok("taviri", ["gave"])]
    got = kinds(learned, "S014", "ma vo 40 taviri", t, fails_only=False,
                gaps=[{"words": "already", "reason": "none"}])
    assert "TIMING" in got


def test_status_sensitive_word_only_upward(learned):
    t = [tok("keth", ["friend"]), tok("tuvan", ["you"]), tok("hesuji", ["laughing"]), tok("ka", ["?"])]
    up = kinds(learned, "S012", "keth, tuvan hesuji ka", t, fails_only=False,
               dropped=[{"words": "old", "reason": "none"}])
    assert "RESPECT_RISK" in up
    t2 = [tok("keth", ["friend"]), tok("tu", ["you"]), tok("veluri", ["came", "back"])]
    assert "RESPECT_RISK" not in kinds(learned, "S007", "keth, tu veluri", t2, fails_only=False)


def test_budget_exhaustion_abstains():
    agent = run_agent(provider=ReplayProvider(REPLAY), cfg={"max_model_calls": 1})
    called = [r["detail"]["key"] for r in agent.log_rows if r["kind"] == "MODEL_CALL"]
    assert called == ["rules_extract"]
    assert all(d["nadi_9_text"] is None for d in agent.decisions.values())
    assert any(r["kind"] == "BUDGET_EXHAUSTED" for r in agent.log_rows)
