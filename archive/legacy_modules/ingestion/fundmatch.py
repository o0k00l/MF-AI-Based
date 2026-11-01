"""
Folio -> Fund resolution. Deterministic, order-independent, self-validating.

This module exists because of a class of defect that is silent and expensive:
when identification was done with keyword rules, a scheme whose dataset id used
an abbreviation was scored against a DIFFERENT manager's similarly named fund,
and a Balanced Advantage scheme was scored with another AMC's BAF metrics. In
both cases the pipeline produced a confident, plausible, wrong number with no
visible defect - and the second one propagated a wrong Mid/Small exposure
downstream into a portfolio allocation.

Notice the failure mode. It was not invented data. It was real data attached to
the wrong entity, which is worse, because nothing looks wrong.

it is to stop using rules. This module scores every candidate independently and
refuses rather than guessing:
  * a folio scoring below a floor                     -> UNRESOLVED
  * two candidates scoring equally well (within delta) -> AMBIGUOUS, id=None
An ambiguous folio is a RESULT, not a failure to be worked around. Applying the
nearest fund metrics to an unresolved folio is exactly the bug above.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
from dataclasses import dataclass
from typing import Iterable, Sequence
from decimal import Decimal
import logging
logger = logging.getLogger(__name__)

# Logging constants
OK, BAD, WARN, INFO = "[ok]", "[!!]", "[..]", "[..]"

_POLICY_CACHE = None

def _resolution_policy() -> dict:
    global _POLICY_CACHE
    if _POLICY_CACHE is None:
        p = Path(__file__).resolve().parents[1] / ".agents" / "knowledge" / "fund_screening_criteria.json"
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            _POLICY_CACHE = data.get("identity_resolution_policy", {})
        except Exception as e:
            logger.warning(r"Failed to load resolution policy: {e}")
            _POLICY_CACHE = {}
    return _POLICY_CACHE

# Tokens that carry no identity.
STOP = {
    "fund", "the", "and", "of", "formerly", "erstwhile", "merged", "scheme", "no", "savings",
}

# Indian mutual-fund naming conventions: the short form used in datasets vs the
# long form printed by the AMC. Portfolio-agnostic.
SYNONYMS = [
    # --- AMC short forms -------------------------------------------------
    # A dataset may abbreviate the AMC while a registry spells it out. Treating
    # "ICICI Pru" and "ICICI Prudential" as different words suppresses the score
    # and drops a resolvable holding out of the analysis entirely.
    (r"\bprudential\b", "prudential"),
    (r"\bpru\b", "prudential"),
    (r"\baditya birla\b", "adityabirla"),
    (r"\babs(?:l)?\b", "adityabirla"),
    (r"\bsbi(?:lf|amc)?\b", "sbi"),
    (r"\baxis\b", "axis"),
    (r"\bhsbc\b", "hsbc"),
    (r"\bkotak mahindra\b", "kotak"),
    (r"\bkotak\b", "kotak"),
    (r"\bmahindra\b", "mahindra"),
    (r"\bcanara robeco\b", "canara"),
    (r"\bcanara\b", "canara"),
    (r"\bparag parikh\b", "paragparikh"),
    (r"\bppfas\b", "paragparikh"),
    (r"\bsbi bluechip\b", "sbi"),
    (r"\bbarclays\b", "barclays"),
    (r"\bbandhan\b", "bandhan"),
    (r"\bnippon\b", "nippon"),
    (r"\bdsp\b", "dsp"),
    (r"\bfi-?i\b", "fi-i"),
    (r"\bquant(?:m)?\b", "quantmpf"),
    (r"\bwhiteoak\b", "whiteoak"),
    (r"\bppf(as)?\b", "paragparikh"),
    # --- compounds first: order is load-bearing ------------------------------
    # A component rule must never rewrite part of a compound before the
    # compound rule runs ("large and mid cap" -> "large and midcap" if the
    # mid-cap rule fires first; the longer rule then can no longer match).
    (r"\blarge\s*&\s*mid\s*cap\b", "largemidcap"),
    (r"\blarge\s+and\s+mid\s+cap\b", "largemidcap"),
    (r"\bnifty\s*india\s*defence\b", "defenceindex"),
    (r"\bbalanced\s+advantage\s+fund\b", "baf"),
    (r"\bbalanced\s+advantage\b", "baf"),
    (r"\bgrowth\s+advantage\b", "baf"),
    (r"\basset\s+allocation\b", "baf"),
    (r"\bcorporate\s+bond\b", "corpdebt"),
    (r"\bmoney\s*market\b", "moneymarket"),
    # --- components ---------------------------------------------------------
    (r"\bflexicap\b", "flexi"),
    (r"\bflexi\s*cap\b", "flexi"),
    (r"\bmid\s*cap\b", "midcap"),
    (r"\blarge\s*cap\b", "largecap"),
    (r"\bmulti\s*cap\b", "multicap"),
    (r"\bsmall\s*cap\b", "smallcap"),
    (r"\barbitrage\b", "arbitrage"),
    (r"\bliquid\b", "liquid"),
    (r"\bgrowt\b", "growth"),
]

_WS = re.compile(r"[^a-z0-9]+")


def normalise(name: str) -> str:
    """Lowercase, drop parentheticals, apply synonyms, collapse separators."""
    s = name.lower()
    s = re.sub(r"\([^)]*\)", " ", s)          # "(formerly <Other Name>)"
    for pat, rep in SYNONYMS:
        s = re.sub(pat, rep, s)
    return _WS.sub(" ", s).strip()


def tokens(name: str) -> set[str]:
    return {t for t in normalise(name).split() if t and t not in STOP}


def key(name: str) -> str:
    return "".join(sorted(tokens(name)))


@dataclass
class Candidate:
    """A fund the folio could belong to. Aliases carry the AMC's long form."""

    id: str
    aliases: tuple[str, ...] = ()
    isin: str | None = None

    def forms(self) -> tuple[str, ...]:
        return (self.id,) + self.aliases


def _score(scheme_toks: set[str], cand: Candidate, all_candidates: Sequence[Candidate]) -> float:
    """Best token-overlap across all of the candidate's surface forms.

    Requires that the scheme name contains at least one token that is unique to
    this candidate (i.e., not shared with any other candidate's PRIMARY form),
    so a generic AMC-only name like "ICICI Prudential Fund" cannot claim to be
    any specific ICICI fund when multiple ICICI funds exist.

    Aliases are used for scoring but NOT for the shared-tokens calculation,
    because aliases are AMC long forms that naturally share many generic tokens
    (e.g., "growth", "regular", "direct") across many funds.
    """
    # Build a set of tokens that appear in more than one candidate's PRIMARY form (id only).
    # Aliases are excluded from shared-tokens because they are AMC long forms that
    # naturally share generic tokens (e.g., "growth", "regular", "direct").
    shared_tokens: set[str] = set()
    for other in all_candidates:
        if other.id == cand.id:
            continue
        shared_tokens |= tokens(other.id)

    best = 0.0
    for form in cand.forms():
        ct = tokens(form)
        if not ct:
            continue
        inter = scheme_toks & ct
        if not inter:
            continue
        # Containment-weighted: how much of the *candidate* is explained.
        jaccard = len(inter) / len(scheme_toks | ct)
        contain = len(inter) / len(ct)
        query_contain = len(inter) / len(scheme_toks) if scheme_toks else 0.0

        if query_contain == 1.0:
            if not (inter - shared_tokens):
                score = 0.70 + 0.05 * contain
            else:
                score = 0.5 * query_contain + 0.5 * contain
        else:
            score = 0.6 * contain + 0.4 * jaccard

        # Require at least one token unique to this candidate's primary form,
        # UNLESS the containment is so high that this is clearly an exact alias
        # match (contain > 0.9), OR the query itself is fully matched (query_contain == 1.0).
        # This allows legitimately ambiguous queries (e.g. "HDFC" across "HDFC Flexi Cap"
        # and "HDFC Mid Cap") to score >= min_score so resolve() returns AMBIGUOUS
        # with runner-up details rather than erroneously discarding to NO_MATCH.
        if contain <= 0.9 and query_contain < 1.0 and not (inter - shared_tokens):
            continue
        best = max(best, score)
    return best


@dataclass(frozen=True)
class Resolution:
    scheme_name: str
    fund_id: str | None
    score: float
    runner_up: str | None
    runner_score: float
    status: str                     # "OK" | "AMBIGUOUS" | "NO_MATCH"

    @property
    def resolved(self) -> bool:
        return self.status == "OK"


def resolve(
    scheme_name: str,
    candidates: Iterable[Candidate],
    min_score: float | None = None,
    margin: float | None = None,
    isin: str | None = None,
) -> Resolution:
    """Map one scheme name to exactly one fund, or refuse."""
    cands_list = list(candidates)

    # GAP-184: Prioritize deterministic statutory 12-character ISIN matching
    import re
    target_isin = (isin or "").strip()
    if not target_isin:
        isin_m = re.search(r'\b(INF[A-Za-z0-9]{9})\b', scheme_name)
        if isin_m:
            target_isin = isin_m.group(1).strip()

    if target_isin:
        target_upper = target_isin.upper()
        for c in cands_list:
            if (c.isin and c.isin.upper() == target_upper) or any(target_upper in a.upper() for a in c.aliases) or target_upper in c.id.upper():
                return Resolution(scheme_name, c.id, 1.0, None, 0.0, "OK")

    policy = _resolution_policy()
    if min_score is None:
        min_score = float(policy.get("min_score", 0.60))
    if margin is None:
        margin = float(policy.get("margin", 0.08))
    exact_thr = float(policy.get("exact_match_threshold", 0.99))

    st = tokens(scheme_name)
    scored = sorted(
        ((_score(st, c, cands_list), c.id) for c in cands_list),
        key=lambda x: x[0], reverse=True
    )
    if not scored or scored[0][0] < min_score:
        top = scored[0][0] if scored else 0.0
        return Resolution(scheme_name, None, top, None, 0.0, "NO_MATCH")
    top_score, top_id = scored[0]
    second_score, second_id = (scored[1] if len(scored) > 1 else (0.0, None))

    # If we have a virtually perfect match, and it's strictly better than the runner-up,
    # the perfect match wins outright regardless of the margin.
    if top_score >= exact_thr and second_score < top_score:
        return Resolution(scheme_name, top_id, top_score, second_id, second_score, "OK")

    if second_id is not None and (top_score - second_score) < margin:
        return Resolution(
            scheme_name, None, top_score, second_id, second_score, "AMBIGUOUS"
        )
    return Resolution(scheme_name, top_id, top_score, second_id, second_score, "OK")
