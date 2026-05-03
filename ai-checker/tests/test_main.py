"""Fast unit tests for ai-checker. No model loading required."""
import pytest

from main import (
    PAT_AI_TIERS,
    ROB_TIERS,
    SentenceResult,
    Tier,
    _chunk_by_sentences,
    _tier_points,
    build_parser,
    combined_risk,
    doc_predict,
    pattern_score,
    split_sentences,
    summarize,
)


def _r(risk: str, scores: dict[str, float] | None = None, qb_type: str | None = None) -> SentenceResult:
    return SentenceResult(
        sentence="x",
        scores=scores or {},
        pat_score=0,
        pat_hits=[],
        risk=risk,
        qb_type=qb_type,
    )


# pattern_score


def test_pattern_score_no_hits_returns_zero():
    weight, hits = pattern_score("This is a perfectly ordinary English sentence.")
    assert weight == 0
    assert hits == []


def test_pattern_score_classic_ai_phrase_fires():
    # IMPORTANT_TO_NOTE pattern is case-sensitive on "it is" — match mid-sentence
    weight, hits = pattern_score("Note that it is important to remember the framework defines the criteria.")
    assert "IMPORTANT_TO_NOTE" in hits
    assert weight >= 3


def test_pattern_score_human_indicator_yields_negative_weight():
    weight, hits = pattern_score("Yesterday I spent an hour debugging a flaky test that only failed in CI.")
    assert "HUMAN_TIME_DEICTIC" in hits
    assert weight < 0


def test_pattern_score_combined_signals_sum():
    weight, hits = pattern_score("Some people believe that it is important to remember this is a way of working.")
    assert "IMPORTANT_TO_NOTE" in hits
    assert "GENERALIZING_PEOPLE" in hits
    from main import RULES
    by_id = {r.id: r.weight for r in RULES}
    assert weight == sum(by_id[h] for h in hits)


# _tier_points


def test_tier_points_no_match_returns_zero():
    tiers = (Tier(0.70, 2), Tier(0.60, 1))
    assert _tier_points(0.50, tiers) == 0.0


def test_tier_points_returns_first_match_strongest_tier():
    tiers = (Tier(0.70, 2), Tier(0.60, 1))
    assert _tier_points(0.85, tiers) == 2
    assert _tier_points(0.65, tiers) == 1


def test_tier_points_strict_greater_than_semantics():
    tiers = (Tier(2, 2), Tier(1, 1))
    # 2 is NOT > 2, falls to next tier
    assert _tier_points(2, tiers) == 1
    # 1 is NOT > 1, no match
    assert _tier_points(1, tiers) == 0.0


def test_pat_ai_tiers_score_integer_pat_scores():
    assert _tier_points(3, PAT_AI_TIERS) == 2
    assert _tier_points(2, PAT_AI_TIERS) == 1
    assert _tier_points(1, PAT_AI_TIERS) == 0
    assert _tier_points(0, PAT_AI_TIERS) == 0


# combined_risk


def test_combined_risk_low_signals_returns_low():
    assert combined_risk({"Rob": 0.1, "DL": 0.2, "G2": 0.05}, pat_score=0) == "LOW"


def test_combined_risk_strong_neural_signals_returns_high():
    assert combined_risk({"Rob": 0.95, "DL": 0.95, "G2": 0.20}, pat_score=3) == "HIGH"


def test_combined_risk_med_tier_threshold():
    # Rob 0.65 → +1; DL 0.70 → +1 (no corroboration boost); G2 0.12 → +0.5
    risk = combined_risk({"Rob": 0.65, "DL": 0.70, "G2": 0.12}, pat_score=0)
    assert risk == "MED"


def test_combined_risk_dl_corroboration_required_for_plus_two():
    # DL > 0.75 alone (Rob low, G2 low) only adds +1, not +2
    risk_alone = combined_risk({"Rob": 0.10, "DL": 0.85, "G2": 0.05}, pat_score=0)
    assert risk_alone == "LOW"
    # DL > 0.75 with Rob > 0.50 corroborates → +2
    risk_corroborated = combined_risk({"Rob": 0.55, "DL": 0.85, "G2": 0.05}, pat_score=0)
    assert risk_corroborated == "MED"


def test_combined_risk_human_pat_score_deducts():
    # Without human-indicator deduction: borderline MED
    risk_no_pat = combined_risk({"Rob": 0.65, "DL": 0.70, "G2": 0.12}, pat_score=0)
    assert risk_no_pat == "MED"
    # Strong human-indicator (pat_score <= -2) drops it to LOW
    risk_with_human = combined_risk({"Rob": 0.65, "DL": 0.70, "G2": 0.12}, pat_score=-3)
    assert risk_with_human == "LOW"


def test_combined_risk_quillbot_ai_label_contributes_three_points():
    # qb_type=AI gives +3; alone that's MED (need 4 for HIGH).
    med_risk = combined_risk(
        {"Rob": 0.5, "DL": 0.5, "G2": 0.05},
        pat_score=0,
        qb_type="AI",
        qb_ai=0.95,
    )
    assert med_risk == "MED"
    # Add a +1 G2 signal and it crosses to HIGH.
    high_risk = combined_risk(
        {"Rob": 0.5, "DL": 0.5, "G2": 0.20},
        pat_score=0,
        qb_type="AI",
        qb_ai=0.95,
    )
    assert high_risk == "HIGH"


# doc_predict


def test_doc_predict_empty_returns_human():
    assert doc_predict([]) == "human"


def test_doc_predict_all_low_returns_human():
    assert doc_predict([_r("LOW")] * 5) == "human"


def test_doc_predict_above_threshold_returns_ai():
    # 3 HIGH out of 5 → score 3/5 = 0.6 > 0.30
    assert doc_predict([_r("HIGH")] * 3 + [_r("LOW")] * 2) == "ai"


def test_doc_predict_at_threshold_boundary():
    # exactly 0.30 should NOT cross (strict >)
    assert doc_predict([_r("HIGH")] * 3 + [_r("LOW")] * 7) == "human"  # 3/10 = 0.30
    assert doc_predict([_r("HIGH")] * 4 + [_r("LOW")] * 6) == "ai"     # 4/10 = 0.40


def test_doc_predict_med_counts_half():
    # 2 MED in 5 sentences = 1.0/5 = 0.20 → human
    assert doc_predict([_r("MED")] * 2 + [_r("LOW")] * 3) == "human"
    # 4 MED in 5 sentences = 2.0/5 = 0.40 → ai
    assert doc_predict([_r("MED")] * 4 + [_r("LOW")] * 1) == "ai"


# summarize


class _FakeEngine:
    def __init__(self, name: str, short: str) -> None:
        self.name = name
        self.short = short

    def score(self, text: str) -> float: return 0.0
    def score_batch(self, texts: list[str]) -> list[float]: return [0.0] * len(texts)


def test_summarize_empty_results():
    s = summarize([], [_FakeEngine("RoBERTa", "Rob")])
    assert s.total == 0
    assert (s.high, s.med, s.low) == (0, 0, 0)
    assert s.engine_averages == {"Rob": 0.0}
    assert s.qb_flagged is None


def test_summarize_counts_tiers():
    results = [_r("HIGH"), _r("HIGH"), _r("MED"), _r("LOW"), _r("LOW")]
    s = summarize(results, [])
    assert (s.total, s.high, s.med, s.low) == (5, 2, 1, 2)


def test_summarize_engine_averages():
    eng = _FakeEngine("RoBERTa", "Rob")
    results = [_r("LOW", scores={"Rob": 0.2}), _r("LOW", scores={"Rob": 0.4})]
    s = summarize(results, [eng])
    assert s.engine_averages["Rob"] == pytest.approx(0.3)


def test_summarize_qb_flagged_only_set_when_qb_data_present():
    no_qb = summarize([_r("LOW"), _r("HIGH")], [])
    assert no_qb.qb_flagged is None

    with_qb = summarize(
        [_r("HIGH", qb_type="AI"), _r("MED", qb_type="HUMAN"), _r("HIGH", qb_type="AI-PARAPHRASED")],
        [],
    )
    assert with_qb.qb_flagged == 2


# _chunk_by_sentences


def test_chunk_by_sentences_under_limit_single_chunk():
    sents = ["one two three.", "four five six."]
    chunks = _chunk_by_sentences(sents, limit=100)
    assert len(chunks) == 1
    assert "one two three" in chunks[0]


def test_chunk_by_sentences_splits_at_limit():
    sents = ["a b c d e.", "f g h i j.", "k l m n o."]  # 5 words each
    chunks = _chunk_by_sentences(sents, limit=10)
    assert len(chunks) == 2  # first 2 fit (10 words), third spills
    assert chunks[1] == "k l m n o."


def test_chunk_by_sentences_single_oversized_sentence_kept_whole():
    huge = " ".join(["word"] * 50)
    chunks = _chunk_by_sentences([huge], limit=10)
    assert chunks == [huge]


# split_sentences


def test_split_sentences_basic():
    sents = split_sentences("First sentence. Second sentence! Third sentence?")
    assert len(sents) == 3
    assert sents[0] == "First sentence."


def test_split_sentences_drops_short_fragments():
    # 'Hi.' is 3 chars, below the 10-char threshold
    sents = split_sentences("Hi. This sentence is long enough to keep.")
    assert len(sents) == 1
    assert sents[0].startswith("This sentence")


def test_split_sentences_empty_text_returns_empty_list():
    assert split_sentences("") == []


# CLI parser


def test_parser_requires_textfile_argument():
    p = build_parser()
    with pytest.raises(SystemExit):
        p.parse_args([])


def test_parser_accepts_textfile_alone():
    args = build_parser().parse_args(["doc.md"])
    assert args.textfile == "doc.md"
    assert args.no_roberta is False
    assert args.no_quillbot is False
    assert args.json is False


def test_parser_engine_skip_flags():
    args = build_parser().parse_args(["doc.md", "--no-roberta", "--no-gpt2"])
    assert args.no_roberta is True
    assert args.no_gpt2 is True
    assert args.no_desklib is False


def test_parser_json_and_no_all_flags():
    args = build_parser().parse_args(["doc.md", "--json", "--no-all"])
    assert args.json is True
    assert args.no_all is True


def test_parser_unknown_flag_errors():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["doc.md", "--no-rberta"])  # typo
