import argparse
import json
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Any, Final, Literal, Protocol

import requests
import torch
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    GPT2LMHeadModel,
    GPT2Tokenizer,
)


Risk = Literal["HIGH", "MED", "LOW"]
DocVerdict = Literal["ai", "human"]


@dataclass
class Rule:
    id: str
    pattern: str
    weight: int

    def __post_init__(self) -> None:
        self.regex: re.Pattern[str] = re.compile(self.pattern)


@dataclass(frozen=True)
class Tier:
    """Inclusive lower-bound rule. Adds `points` when value > threshold."""
    threshold: float
    points: float


@dataclass
class QBMatch:
    type: str
    ai_score: float


@dataclass
class SentenceResult:
    sentence: str
    scores: dict[str, float]
    pat_score: int
    pat_hits: list[str]
    risk: Risk
    qb_type: str | None = None
    qb_ai: float = 0.0


@dataclass
class Summary:
    total: int
    high: int
    med: int
    engine_averages: dict[str, float]
    qb_flagged: int | None

    @property
    def low(self) -> int:
        return self.total - self.high - self.med


RULES: list[Rule] = [
    Rule("COMMA_LIST_4PLUS", r'(?:,\s*\w[\w\s]*){3,}\s+and\s+', 3),
    Rule("PURPOSE_TAIL", r'\bfor\s+\w+(?:\s+\w+)?\s+and\s+\w+\.\s*$', 2),
    Rule("THEY_ALSO", r'\bThey\s+also\b', 3),
    Rule("FIRST_SECOND", r'\bFirst[,.].*\bSecond[,.]', 3),
    Rule("BOTH_DEPLOYED", r'\bboth\s+\w+ed\b', 2),
    Rule("WILL_PRIMARILY", r'\bwill\s+primarily\b', 2),
    Rule("FOCUSES_ON", r'\bfocuses\s+on\b.*,.*,', 3),
    Rule("WHICH_CLAUSE", r',\s*which\s+\w+s\s+\w+', 2),
    Rule("VERIFY_COMPLIANCE", r'\b(?:verify|ensure)\s+(?:compliance|conformance)\b', 3),
    Rule("PARALLEL_SVO", r'[A-Z]\w+\s+\w+s\s+\w[\w\s]{3,20}\.\s+[A-Z]\w+\s+\w+s\s+\w[\w\s]{3,20}\.', 2),
    Rule("ESTABLISHED_BY", r'\b(?:established|defined)\s+by\s+the\b', 2),
    Rule("MUST_SATISFY", r'\bmust\s+(?:satisfy|meet|adhere|comply)\b', 2),
    Rule("TRIPLE_VERB", r'\b\w+(?:es|s)\s+\w[\w\s]+,\s+\w+(?:es|s)\s+\w[\w\s]+\s+and\s+\w+(?:es|s)\s+', 2),
    Rule("ARE_ASSESSED", r'\bare\s+\w+ed\s+as\s+well\b', 2),
    Rule("FOR_X_CRITERIA", r'\bFor\s+\w+,?\s+the\s+(?:criteria|guidelines|requirements)\b', 2),
    Rule("TWO_KEY", r'\b(?:two|three|four)\s+(?:key|main|primary|core)\b', 2),
    Rule("DURING_WP_TESTS", r'\bDuring\s+WP\d+,\s+\w+\s+tests?\s+(?:covered|validated|checked)\b', 2),
    Rule("TECH_POWERS", r'\b\w+\s+(?:powers?|handles?)\s+(?:the\s+)?\w+\s+\w+', 2),
    Rule("PAREN_ABBREV_LIST", r'\([A-Z]{2,}\)[,\s]+\w+[^.]{5,}\([A-Z]{2,}\)', 2),
    Rule("IMPORTANT_TO_NOTE", r"\b(?:it\s+is|it'?s)\s+important\s+to\s+(?:note|remember|consider|recognize|understand|keep\s+in\s+mind)\b", 3),
    Rule("FEW_REASONS_WHY", r"\b(?:there\s+are\s+(?:a\s+)?few|a\s+few)\s+reasons?\s+why\b", 3),
    Rule("ALSO_KNOWN_AS", r"\b(?:is|are)\s+also\s+known\s+as\b", 2),
    Rule("IS_TYPE_OF", r"\b(?:is|are)\s+a\s+type\s+of\b", 2),
    Rule("HOWEVER_IT_IS", r"\bhowever,?\s+it\s+is\b", 2),
    Rule("THIS_MEANS_THAT", r"\bthis\s+means\s+that\b", 2),
    Rule("GOOD_IDEA_TO", r"\bit\s+(?:is|would\s+be)\s+a\s+good\s+idea\s+to\b", 3),
    Rule("THERE_ARE_SEVERAL", r"\bthere\s+are\s+several\s+(?:ways|reasons|factors|things|methods|approaches)\b", 3),
    Rule("ENUM_OPENER", r"^(?:First|Second|Third|Fourth|Fifth|Finally|Lastly),\s+\w", 2),
    Rule("GENERALIZING_PEOPLE", r"\b(?:Some|Other|Many)\s+people\s+\w+\b", 3),
    Rule("FORMAL_DEFINITION", r"\b(?:is|are)\s+a\s+(?:\w+\s+){0,2}(?:way|type|form|kind|method|process|technique|approach|cocktail|response|test|tool|practice)\b", 3),
    Rule("IMPERSONAL_ITS_WAY", r"\bIt'?s\s+(?:a\s+(?:way|type|form|kind))\b", 3),
    Rule("JUST_LIKE_HOW", r"\b[Jj]ust\s+like\s+(?:how|when)\b", 3),
    Rule("FEW_SIMPLE_TESTS", r"\bthere\s+are\s+(?:a\s+)?few\s+(?:simple\s+)?(?:ways|methods|tests|things|tips|examples|options|steps)\b", 3),
    Rule("HUMAN_TIME_DEICTIC", r"\b(?:[Yy]esterday|[Tt]omorrow|[Ll]ast\s+(?:week|month|year|night|Friday|Saturday|Sunday|Monday|Tuesday|Wednesday|Thursday)|[Tt]his\s+morning|[Tt]onight|[Rr]ight\s+now|[Aa]\s+few\s+(?:minutes|hours|days)\s+ago)\b", -2),
    Rule("HUMAN_PERSONAL_RELATION", r"\bmy\s+(?:kid|kids|wife|husband|partner|family|son|daughter|mom|dad|mother|father|friend|colleague|boss|coffee|car|cat|dog|plant|office|desk|home)\b", -3),
    Rule("HUMAN_CASUAL_INTERJECTION", r"(?:^|\.\s+)(?:[Aa]nnoying|[Aa]nyway|[Aa]nyhow|[Hh]onestly|[Ff]rankly|[Tt]urns?\s+out|[Hh]uh|[Ww]ow|[Yy]ikes|[Dd]amn|[Mm]eh|[Oo]of)[\.,]", -2),
    Rule("HUMAN_FIRST_PERSON_OPINION", r"\b(?:[Pp]ersonally,?\s+I|I\s+(?:believe|think|prefer|always|usually|tend\s+to|would|wouldn'?t|don'?t|did\s+n'?t|tried|guess|feel|reckon|suspect)|in\s+my\s+(?:opinion|experience|view)|as\s+far\s+as\s+I\s+(?:know|can\s+tell))\b", -2),
]

RESULTS_FILE: Final = Path("/tmp/ai-checker-results.json")

# combined_risk rubric. Tiers are first-match-wins, ordered by descending strength.
# Thresholds and points are tuned together; changing one without re-evaluating
# the others can flip many sentences across the HIGH/MED/LOW boundaries.
HIGH_RISK_POINTS: Final = 4.0
MED_RISK_POINTS: Final = 2.0
ROB_TIERS: Final = (Tier(0.70, 2), Tier(0.60, 1))
G2_TIERS: Final = (Tier(0.15, 1), Tier(0.10, 0.5))
DL_BASE_TIER: Final = Tier(0.65, 1)
DL_CORROBORATED_TIER: Final = Tier(0.75, 2)
DL_CORROBORATING_ROB: Final = 0.50
DL_CORROBORATING_G2: Final = 0.15
PAT_AI_TIERS: Final = (Tier(2, 2), Tier(1, 1))
PAT_HUMAN_THRESHOLD: Final = -2
PAT_HUMAN_DEDUCTION: Final = -2
QB_AI_LABELS: Final = frozenset({"AI", "AI-PARAPHRASED"})
QB_TYPE_HUMAN: Final = "HUMAN"
QB_AI_LABEL_POINTS: Final = 3
QB_AI_FRACTION_THRESHOLD: Final = 0.5
QB_AI_FRACTION_POINTS: Final = 1
DOC_THRESHOLD: Final = 0.30

# Engine + network configuration
DESKLIB_MIN_WORDS: Final = 8
DESKLIB_NEUTRAL_SCORE: Final = 0.5
ROBERTA_MAX_TOKENS: Final = 512
DESKLIB_MAX_TOKENS: Final = 768
GPT2_MAX_TOKENS: Final = 1024
QB_WORD_LIMIT: Final = 1100
QB_KEY_LENGTH: Final = 80
QB_FUZZY_MATCH_LENGTH: Final = 40
QB_REQUEST_TIMEOUT_SECONDS: Final = 60
QB_CHUNK_DELAY_SECONDS: Final = 2
PLAYWRIGHT_PAGE_SETTLE_MS: Final = 2000
PLAYWRIGHT_BANNER_TIMEOUT_MS: Final = 3000


class Scorer(Protocol):
    name: str
    short: str

    def score(self, text: str) -> float: ...
    def score_batch(self, texts: list[str]) -> list[float]: ...


def _status(msg: str) -> None:
    print(msg, file=sys.stderr)


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if len(s.strip()) >= 10]


def pattern_score(sentence: str) -> tuple[int, list[str]]:
    hits: list[str] = []
    weight = 0
    for rule in RULES:
        if rule.regex.search(sentence):
            hits.append(rule.id)
            weight += rule.weight
    return weight, hits


def _tier_points(value: float, tiers: tuple[Tier, ...]) -> float:
    """Return points from the strongest tier the value clears, else 0."""
    return next((t.points for t in tiers if value > t.threshold), 0.0)


class RobertaEngine:
    name = "RoBERTa"
    short = "Rob"

    def __init__(self, device: str) -> None:
        _status("  Loading RoBERTa (roberta-large-openai-detector)...")
        self.tokenizer = AutoTokenizer.from_pretrained("roberta-large-openai-detector")
        self.model = AutoModelForSequenceClassification.from_pretrained("roberta-large-openai-detector").to(device).eval()
        self.device = device

    def score(self, text: str) -> float:
        return self.score_batch([text])[0]

    def score_batch(self, texts: list[str]) -> list[float]:
        if not texts:
            return []
        inputs = self.tokenizer(texts, return_tensors="pt", truncation=True, padding=True, max_length=ROBERTA_MAX_TOKENS)
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        with torch.no_grad():
            logits = self.model(**inputs).logits
        return torch.softmax(logits, dim=-1)[:, 0].cpu().tolist()


class DesklibEngine:
    name = "Desklib"
    short = "DL"

    def __init__(self, device: str) -> None:
        _status("  Loading Desklib (DeBERTa-v3-large)...")
        import torch.nn as nn
        from huggingface_hub import hf_hub_download
        from safetensors.torch import load_file
        from transformers import AutoConfig, DebertaV2Model

        model_id = "desklib/ai-text-detector-v1.01"
        self.tokenizer = AutoTokenizer.from_pretrained(model_id)
        config = AutoConfig.from_pretrained(model_id)
        # The published checkpoint wraps DebertaV2Model with a `model.` prefix
        # plus a custom 1-output classifier head. Strip the prefix and lift the
        # head out by hand — no `AutoModelForSequenceClassification` covers this.
        raw_state = load_file(hf_hub_download(model_id, "model.safetensors"))
        base_state, cls_weights = {}, {}
        for k, v in raw_state.items():
            if k.startswith("classifier."):
                cls_weights[k] = v
            elif k.startswith("model."):
                base_state[k[6:]] = v
            else:
                base_state[k] = v
        self.base = DebertaV2Model(config)
        self.base.load_state_dict(base_state, strict=False)
        self.head = nn.Linear(config.hidden_size, 1)
        self.head.weight.data = cls_weights["classifier.weight"]
        self.head.bias.data = cls_weights["classifier.bias"]
        self.base = self.base.to(device).eval()
        self.head = self.head.to(device).eval()
        self.device = device

    def score(self, text: str) -> float:
        return self.score_batch([text])[0]

    def score_batch(self, texts: list[str]) -> list[float]:
        if not texts:
            return []
        # Short sentences cause Desklib to over-fire on terse human writing;
        # short-circuit them to a neutral score instead of paying the model cost.
        long_idx = [i for i, t in enumerate(texts) if len(t.split()) >= DESKLIB_MIN_WORDS]
        out: list[float] = [DESKLIB_NEUTRAL_SCORE] * len(texts)
        if not long_idx:
            return out
        long_texts = [texts[i] for i in long_idx]
        inputs = self.tokenizer(long_texts, return_tensors="pt", truncation=True, padding=True, max_length=DESKLIB_MAX_TOKENS)
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        with torch.no_grad():
            hidden = self.base(**inputs).last_hidden_state
            mask = inputs["attention_mask"].unsqueeze(-1).expand(hidden.size()).float()
            pooled = (hidden * mask).sum(1) / mask.sum(1)
            scores = torch.sigmoid(self.head(pooled)).squeeze(-1).cpu().tolist()
        for orig_i, s in zip(long_idx, scores):
            out[orig_i] = s
        return out


class GPT2Engine:
    name = "GPT-2"
    short = "G2"

    def __init__(self, device: str) -> None:
        _status("  Loading GPT-2 (perplexity detector)...")
        self.tokenizer = GPT2Tokenizer.from_pretrained("gpt2")
        self.tokenizer.pad_token = self.tokenizer.eos_token
        self.model = GPT2LMHeadModel.from_pretrained("gpt2").to(device).eval()
        self.device = device

    def score(self, text: str) -> float:
        return self.score_batch([text])[0]

    def score_batch(self, texts: list[str]) -> list[float]:
        if not texts:
            return []
        inputs = self.tokenizer(texts, return_tensors="pt", truncation=True, padding=True, max_length=GPT2_MAX_TOKENS)
        ids = inputs["input_ids"].to(self.device)
        mask = inputs["attention_mask"].to(self.device)
        if ids.shape[1] < 2:
            return [0.0] * len(texts)
        with torch.no_grad():
            logits = self.model(ids).logits
        shifted_logits = logits[:, :-1, :]
        shifted_ids = ids[:, 1:].unsqueeze(-1)
        shifted_mask = mask[:, 1:].float()
        token_probs = torch.softmax(shifted_logits, dim=-1).gather(-1, shifted_ids).squeeze(-1)
        sums = (token_probs * shifted_mask).sum(dim=-1)
        counts = shifted_mask.sum(dim=-1).clamp(min=1)
        means = (sums / counts).cpu().tolist()
        actual_lens = mask.sum(dim=-1).cpu().tolist()
        return [m if al >= 2 else 0.0 for m, al in zip(means, actual_lens)]


def doc_predict(results: list[SentenceResult]) -> DocVerdict:
    if not results:
        return "human"
    counts = Counter(r.risk for r in results)
    score = counts["HIGH"] + 0.5 * counts["MED"]
    return "ai" if score / len(results) > DOC_THRESHOLD else "human"


QB_USER_AGENT: Final = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
QB_POST_HEADERS: Final[dict[str, str]] = {
    "Content-Type": "application/json",
    "Origin": "https://quillbot.com",
    "Referer": "https://quillbot.com/ai-content-detector",
    "User-Agent": QB_USER_AGENT,
}


def quillbot_session() -> dict[str, str]:
    """Bootstrap a QuillBot session via Playwright — QuillBot sets
    JS-only cookies that a plain requests.Session() can't capture, so
    we need a real browser to load the page and harvest cookies."""
    from playwright.sync_api import sync_playwright

    _status("  Getting QuillBot session...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=QB_USER_AGENT,
        )
        page = ctx.new_page()
        page.goto("https://quillbot.com/ai-content-detector", wait_until="networkidle")
        page.wait_for_timeout(PLAYWRIGHT_PAGE_SETTLE_MS)
        # Cookie banner is optional — proceed if it doesn't appear.
        try:
            page.click("button:has-text('Accept')", timeout=PLAYWRIGHT_BANNER_TIMEOUT_MS)
        except Exception:
            pass
        cookies = {c["name"]: c["value"] for c in ctx.cookies() if "quillbot" in c.get("domain", "")}
        browser.close()
    _status(f"  Got {len(cookies)} cookies")
    return cookies


def quillbot_scan(text: str, cookies: dict[str, str]) -> dict[str, QBMatch]:
    total_words = len(text.split())
    if total_words <= QB_WORD_LIMIT:
        chunks = [text]
    else:
        chunks = _chunk_by_sentences(split_sentences(text), QB_WORD_LIMIT)
    if len(chunks) > 1:
        _status(f"  QuillBot: {total_words} words -> {len(chunks)} chunks")
    matches: dict[str, QBMatch] = {}
    for i, chunk in enumerate(chunks):
        resp = requests.post(
            "https://quillbot.com/api/ai-detector/score",
            json={"text": chunk}, headers=QB_POST_HEADERS, cookies=cookies,
            timeout=QB_REQUEST_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        for c in _parse_qb_chunks(resp.json()):
            ct = c.get("text", "").strip()
            for sent in split_sentences(ct):
                matches[sent[:QB_KEY_LENGTH]] = QBMatch(
                    type=c.get("type", QB_TYPE_HUMAN),
                    ai_score=float(c.get("aiScore", 0)),
                )
        if i < len(chunks) - 1:
            time.sleep(QB_CHUNK_DELAY_SECONDS)
    return matches


def _parse_qb_chunks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not payload or "data" not in payload:
        return []
    return payload["data"].get("value", {}).get("chunks", [])


def _chunk_by_sentences(sentences: list[str], limit: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    words = 0
    for sent in sentences:
        wc = len(sent.split())
        if words + wc > limit and current:
            chunks.append(" ".join(current))
            current, words = [sent], wc
        else:
            current.append(sent)
            words += wc
    if current:
        chunks.append(" ".join(current))
    return chunks


def combined_risk(
    scores: dict[str, float],
    pat_score: int,
    qb_type: str | None = None,
    qb_ai: float = 0.0,
) -> Risk:
    rob = scores.get("Rob", 0.0)
    g2 = scores.get("G2", 0.0)
    dl = scores.get("DL", 0.0)
    points = _tier_points(rob, ROB_TIERS) + _tier_points(g2, G2_TIERS)
    points += _desklib_points(dl, rob, g2)
    points += _pattern_points(pat_score)
    points += _quillbot_points(qb_type, qb_ai)
    if points >= HIGH_RISK_POINTS:
        return "HIGH"
    if points >= MED_RISK_POINTS:
        return "MED"
    return "LOW"


def _desklib_points(dl: float, rob: float, g2: float) -> float:
    corroborated = rob > DL_CORROBORATING_ROB or g2 > DL_CORROBORATING_G2
    if dl > DL_CORROBORATED_TIER.threshold and corroborated:
        return DL_CORROBORATED_TIER.points
    if dl > DL_BASE_TIER.threshold:
        return DL_BASE_TIER.points
    return 0.0


def _pattern_points(pat_score: int) -> float:
    points = _tier_points(pat_score, PAT_AI_TIERS)
    if pat_score <= PAT_HUMAN_THRESHOLD:
        points += PAT_HUMAN_DEDUCTION
    return points


def _quillbot_points(qb_type: str | None, qb_ai: float) -> float:
    if qb_type in QB_AI_LABELS:
        return QB_AI_LABEL_POINTS
    if qb_ai > QB_AI_FRACTION_THRESHOLD:
        return QB_AI_FRACTION_POINTS
    return 0.0


def _match_qb(sent: str, qb_results: dict[str, QBMatch]) -> QBMatch | None:
    direct = qb_results.get(sent[:QB_KEY_LENGTH])
    if direct:
        return direct
    head = sent[:QB_FUZZY_MATCH_LENGTH]
    for qk, qv in qb_results.items():
        if head in qk or qk[:QB_FUZZY_MATCH_LENGTH] in sent:
            return qv
    return None


def analyze(
    text: str,
    engines: list[Scorer],
    qb_results: dict[str, QBMatch] | None = None,
) -> list[SentenceResult]:
    sentences = split_sentences(text)
    if not sentences:
        return []
    engine_scores = {e.short: e.score_batch(sentences) for e in engines}
    return [_build_result(sent, i, engine_scores, qb_results) for i, sent in enumerate(sentences)]


def _build_result(
    sent: str,
    i: int,
    engine_scores: dict[str, list[float]],
    qb_results: dict[str, QBMatch] | None,
) -> SentenceResult:
    scores = {short: vals[i] for short, vals in engine_scores.items()}
    pat, pat_hits = pattern_score(sent)
    qb_type, qb_ai = None, 0.0
    if qb_results:
        match = _match_qb(sent, qb_results)
        if match:
            qb_type, qb_ai = match.type, match.ai_score
    return SentenceResult(
        sentence=sent,
        scores=scores,
        pat_score=pat,
        pat_hits=pat_hits,
        risk=combined_risk(scores, pat, qb_type, qb_ai),
        qb_type=qb_type,
        qb_ai=qb_ai,
    )


def summarize(results: list[SentenceResult], engines: list[Scorer]) -> Summary:
    counts = Counter(r.risk for r in results)
    engine_averages = {
        e.short: fmean(r.scores.get(e.short, 0) for r in results) if results else 0.0
        for e in engines
    }
    has_qb = any(r.qb_type is not None for r in results)
    qb_flagged = sum(1 for r in results if r.qb_type in QB_AI_LABELS) if has_qb else None
    return Summary(
        total=len(results),
        high=counts["HIGH"],
        med=counts["MED"],
        engine_averages=engine_averages,
        qb_flagged=qb_flagged,
    )


def print_results(results: list[SentenceResult], engines: list[Scorer], hide_low: bool = False) -> None:
    has_qb = any(r.qb_type is not None for r in results)
    bar = "=" * 110
    hdr = " ".join(f"{e.short:<5}" for e in engines)
    qb_hdr = "QB             " if has_qb else ""
    print(f"\n{bar}")
    print(f"{'RISK':<6} {hdr} {'Pat':<4} {qb_hdr}SENTENCE")
    print(bar)
    for r in results:
        if hide_low and r.risk == "LOW":
            continue
        print(_format_row(r, engines, has_qb))
        if r.pat_hits:
            print(f"       patterns: {', '.join(r.pat_hits)}")
    _print_summary(summarize(results, engines), engines, bar)


def _format_row(r: SentenceResult, engines: list[Scorer], has_qb: bool) -> str:
    marker = {"HIGH": " <<<< FLAG", "MED": " << warn"}.get(r.risk, "")
    sc = " ".join(f"{r.scores.get(e.short, 0):.0%}  " for e in engines)
    qb = ""
    if has_qb:
        qt = (r.qb_type or "?")[:12]
        qb = f"{qt:<12} {r.qb_ai:.0%} "
    preview_len = 60 if has_qb else 70
    preview = r.sentence[:preview_len] + ("..." if len(r.sentence) > preview_len else "")
    return f"{r.risk:<6} {sc}{r.pat_score:<4} {qb}{preview}{marker}"


def _print_summary(s: Summary, engines: list[Scorer], bar: str) -> None:
    avg_str = " | ".join(f"{e.name}: {s.engine_averages.get(e.short, 0):.0%}" for e in engines)
    print(f"\n{bar}")
    print(f"SUMMARY: {s.total} sentences | HIGH: {s.high} | MED: {s.med} | LOW: {s.low}")
    print(f"  Averages: {avg_str}")
    if s.qb_flagged is not None:
        print(f"  QuillBot AI-flagged: {s.qb_flagged}")
    print(f"{bar}\n")


def results_to_json(results: list[SentenceResult], engines: list[Scorer]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in results:
        entry: dict[str, Any] = {
            "sentence": r.sentence,
            "risk": r.risk,
            "pattern_score": r.pat_score,
            "pattern_hits": r.pat_hits,
        }
        for e in engines:
            entry[f"{e.name.lower()}_pct"] = round(r.scores.get(e.short, 0) * 100, 1)
        if r.qb_type is not None:
            entry["quillbot_type"] = r.qb_type
            entry["quillbot_ai_pct"] = round(r.qb_ai * 100, 1)
        out.append(entry)
    return out


def results_to_compact_json(results: list[SentenceResult], engines: list[Scorer]) -> list[dict[str, Any]]:
    return [{
        "sentence": r.sentence,
        "risk": r.risk,
        **{e.short: round(r.scores.get(e.short, 0) * 100, 1) for e in engines},
        "pattern": r.pat_score,
    } for r in results]


def build_engines(device: str, use_roberta: bool, use_desklib: bool, use_gpt2: bool) -> list[Scorer]:
    engines: list[Scorer] = []
    if use_roberta:
        engines.append(RobertaEngine(device))
    if use_desklib:
        engines.append(DesklibEngine(device))
    if use_gpt2:
        engines.append(GPT2Engine(device))
    return engines


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ai-checker",
        description="Multi-engine AI text detection (RoBERTa-large + Desklib DeBERTa-v3 + GPT-2 + QuillBot + patterns)",
    )
    p.add_argument("textfile", help="path to a UTF-8 text file to classify")
    p.add_argument("--no-roberta", action="store_true", help="skip RoBERTa-large (roberta-large-openai-detector)")
    p.add_argument("--no-desklib", action="store_true", help="skip Desklib DeBERTa-v3-large")
    p.add_argument("--no-gpt2", action="store_true", help="skip GPT-2 perplexity")
    p.add_argument("--no-quillbot", action="store_true", help="skip QuillBot API (no network)")
    p.add_argument("--no-all", action="store_true", help="hide LOW-risk sentences (show only MED/HIGH)")
    p.add_argument("--json", action="store_true", help="emit JSON to stdout instead of human-readable table")
    return p


def _read_text(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"error: file not found: {path}", file=sys.stderr)
        raise SystemExit(2)
    except UnicodeDecodeError as e:
        print(f"error: {path} is not valid UTF-8 ({e.reason})", file=sys.stderr)
        raise SystemExit(2)


def _run_quillbot(text: str) -> dict[str, QBMatch] | None:
    try:
        cookies = quillbot_session()
        matches = quillbot_scan(text, cookies)
        _status(f"  QuillBot returned {len(matches)} sentence scores")
        return matches
    except Exception as e:
        _status(f"  QuillBot failed: {e}")
        return None


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    text = _read_text(args.textfile)
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    _status(f"Device: {device}\nLoading engines...")
    engines = build_engines(device, not args.no_roberta, not args.no_desklib, not args.no_gpt2)
    _status(f"  Active: {', '.join(e.name for e in engines)} + patterns")

    qb_results = None if args.no_quillbot else _run_quillbot(text)
    results = analyze(text, engines, qb_results)

    if args.json:
        print(json.dumps(results_to_json(results, engines), indent=2))
    else:
        print_results(results, engines, hide_low=args.no_all)
    RESULTS_FILE.write_text(json.dumps(results_to_compact_json(results, engines), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
