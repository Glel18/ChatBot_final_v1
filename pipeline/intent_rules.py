"""
intent_rules.py

A deterministic, rule-only alternative to structured_intent.py's LLM call:
scores intent/action/answer_type by counting weighted keyword-indicator
phrase hits, and only commits when the top score clears a minimum AND
beats the runner-up by a margin -- otherwise it abstains, and the caller
(structured_intent.py) falls through to the LLM exactly as it does today.
No model call, no I/O -- same "pure rules, no lookups" shape date_rules.py
already establishes in this pipeline, and for the same reason: this
sub-problem (does the message contain enough unambiguous signal to commit
without a model?) is answerable by fixed phrase lists for a real fraction
of messages, without needing to ask an LLM every time.

Adapted from v1's structured_intent/rule_engine.py -- the SCORING
MECHANISM (word-boundary phrase matching weighted by phrase word-count,
top-score-and-margin gate, precedence tie-break) is the same proven
approach (v1's own gold-set eval: 16/16 correct). The INDICATOR PHRASES
below are NOT ported -- v1's taxonomy has no `complaint` intent at all (it
folds fault reports into request_service + action "declare"), so v1's
actual phrase lists (which include bare "θέλω" as a request_service
indicator) were never tested against v2's specific complaint-vs-
request_service ambiguity (open-weakpoints.md #7) and would reintroduce
it. Every indicator list below was built and tested fresh against v2's
real taxonomy and known trouble cases -- see notes/fix-016 for the full
gold-set evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from entity_extraction import normalize_for_comparison

# Below this score, there's no real signal -- abstain rather than guess.
# Below this margin over the runner-up, there's signal but it's not
# decisive -- also abstain. Same values and same reasoning as v1's
# rule_engine.py (MIN_SCORE = 1, MIN_MARGIN = 1): starting points, not
# final answers -- same "needs calibration against real testing" posture
# every other threshold in this pipeline uses (see gazetteer.MIN_MATCH_SCORE).
MIN_SCORE = 1
MIN_MARGIN = 1

# complaint ranked above request_service as a secondary backstop for
# open-weakpoints.md #7 -- the indicator phrases below are the PRIMARY
# defense (request_service's list has no bare "θέλω"/"θέλω να", so a real
# complaint like "θέλω να υποβάλω παράπονο" scores 0 there and can't tie
# complaint in the first place), but if some future phrase addition ever
# does cause an exact tie, precedence should resolve it toward the
# minority-but-costlier-to-miss category rather than arbitrarily. Same
# belt-and-suspenders pattern fix-013/fix-014 use for kb_match (a score
# threshold AND a word-overlap gate, not just one).
_INTENT_PRECEDENCE = ("complaint", "request_service", "question", "other")

# Every request_service phrase names a concrete action -- deliberately NO
# bare "θέλω"/"θέλω να" anywhere in this list. v1's config.json lists bare
# "θέλω" as a request_service indicator; that's specifically what let
# "θέλω να υποβάλω παράπονο..." (I want to file a COMPLAINT) drift toward
# request_service in testing (open-weakpoints.md #7) -- removing the bare
# phrasing signal entirely, not just weighting it lower, removes the
# tension structurally instead of tuning around it.
INTENT_INDICATORS = {
    "request_service": [
        "θέλω να κάνω αίτηση", "κάνω αίτηση", "θα ήθελα να κάνω αίτηση",
        "να υποβάλω αίτηση", "θέλω να υποβάλω αίτηση",
        "θέλω να εκδώσω", "θέλω να ανανεώσω", "θέλω να πληρώσω",
        "θέλω να ακυρώσω", "χρειάζομαι να κλείσω ραντεβού",
        "θέλω να κλείσω ραντεβού", "να κλείσω ραντεβού",
    ],
    "question": [
        "πόσο κοστίζει", "πόσο κοστίζουν", "πόσο χρόνο", "τι δικαιολογητικά",
        "τι χρειάζομαι", "ποιες ώρες", "ποιο είναι το τηλέφωνο", "πού μπορώ",
        "είστε ανοιχτά", "θέλω να μάθω", "θέλω να ρωτήσω", "πώς μπορώ να μάθω",
    ],
    "complaint": [
        "παράπονο", "καταγγελία", "καταγγέλλω", "θέλω να υποβάλω παράπονο",
        "υποβάλω παράπονο", "δεν λειτουργεί", "υπάρχει πρόβλημα",
        "δεν έχω λάβει απάντηση", "είναι χαλασμένο", "είναι επικίνδυνο",
        "εδώ και μέρες", "εδώ και εβδομάδες", "εδώ και μια εβδομάδα",
    ],
    # Deliberately short/low-weight (bare 1-word greetings): the
    # phrase-length weighting in _count_hits means any real content
    # signal elsewhere in the same message outweighs a greeting prefix
    # automatically -- this is the structural answer to open-weakpoints.md
    # #3 (greeting-prefixed questions initially looking misclassified),
    # not a special-cased rule.
    "other": ["γεια", "καλημέρα", "καλησπέρα", "ευχαριστώ"],
}

# Distinct verb stems per action -- "schedule" and "cancel" share no
# vocabulary (no reliance on the word "ραντεβού" alone, which appears in
# both a booking AND a cancellation message). Directly fixes the
# open-weakpoints.md #5 / fix-011 regression ("Χρειάζομαι να κλείσω
# ραντεβού" being misread as "cancel") without touching the LLM path's
# ACTIONS prompt at all -- messages this confident about the verb never
# reach that ambiguous bare-word-list prompt in the first place.
ACTION_INDICATORS = {
    "apply": ["κάνω αίτηση", "υποβάλω αίτηση", "αιτούμαι"],
    "renew": ["ανανεώσω", "ανανέωση"],
    "check_status": ["τι κατάσταση έχει", "πού βρίσκεται η αίτησή μου", "έχει εκδοθεί"],
    "pay": ["πληρώσω", "εξοφλήσω", "καταβάλω"],
    "cancel": ["ακυρώσω", "ακύρωση", "να ακυρώσω"],
    "schedule": ["κλείσω ραντεβού", "να κλείσω ραντεβού", "κλείσω ένα ραντεβού"],
    # "unknown" is the default when nothing scores -- not itself scored.
}

ANSWER_TYPE_INDICATORS = {
    "cost": ["κοστίζει", "κοστίζουν", "κόστος", "τιμή", "χρέωση", "τέλη"],
    "deadline": ["πόσο χρόνο", "μέχρι πότε", "προθεσμία"],
    "requirements": ["δικαιολογητικά", "τι χρειάζομαι", "τι έγγραφα"],
    "contact": ["τηλέφωνο", "email", "στοιχεία επικοινωνίας"],
    "procedure": ["πώς κάνω", "διαδικασία", "πώς μπορώ"],
    # "other" is the default when nothing scores -- not itself scored.
}


@dataclass
class FastPathResult:
    """
    Mirrors just enough of structured_intent.py's record shape for
    _try_fast_path to build a full record from -- does NOT include
    `entities`/`kb_match`/`constraints`: this module knows nothing about
    the KB or the final record shape (same separation date_rules.py
    already models -- find_dates returns entities, not a whole record).
    """
    resolved: bool
    intent: str | None = None
    action: str | None = None
    answer_type: str | None = None
    service: str | None = None
    abstain_reason: str | None = None  # "no_signal" | "low_margin" | "no_service_entity"
    scores: dict[str, int] = field(default_factory=dict)


def _phrase_matches(normalized_text: str, phrase: str) -> bool:
    """
    Word-boundary match, not raw substring containment -- same reasoning
    v1's rule_engine.py already documents: accent-stripping can collapse
    two different words to the same string (e.g. "πού"/where and
    "που"/that-who both normalize to "που"), which would otherwise match
    as a false substring hit inside an unrelated longer word.
    """
    pattern = r"\b" + re.escape(normalize_for_comparison(phrase)) + r"\b"
    return re.search(pattern, normalized_text) is not None


def _count_hits(normalized_text: str, phrases: list[str]) -> int:
    """
    Weighted by phrase word-count: a longer, more specific phrase match
    outweighs a generic single-word one. Without this, a broad indicator
    like a bare greeting could tie with -- or beat -- a more specific
    multi-word phrase for a completely different category.
    """
    return sum(len(phrase.split()) for phrase in phrases if _phrase_matches(normalized_text, phrase))


def _top_two(scores: dict[str, int], precedence: tuple[str, ...]) -> tuple[str, int, int]:
    """Returns (top_key, top_score, runner_up_score). Ties broken by precedence order."""
    precedence_rank = {name: i for i, name in enumerate(precedence)}
    ordered = sorted(
        scores.items(),
        key=lambda kv: (-kv[1], precedence_rank.get(kv[0], len(precedence))),
    )
    top_key, top_score = ordered[0]
    runner_up_score = ordered[1][1] if len(ordered) > 1 else 0
    return top_key, top_score, runner_up_score


def _resolve_action(normalized: str) -> str:
    """Simpler than intent resolution -- no margin gate, just top score vs
    MIN_SCORE, same as v1's own resolve_action. Lower stakes than a wrong
    intent: answer_composition.py already has a safe "unknown" branch."""
    scores = {a: _count_hits(normalized, phrases) for a, phrases in ACTION_INDICATORS.items()}
    top_action, top_score = max(scores.items(), key=lambda kv: kv[1])
    return top_action if top_score >= MIN_SCORE else "unknown"


def _resolve_answer_type(normalized: str, top_intent: str) -> str:
    """Same top-score-vs-MIN_SCORE pattern as _resolve_action; falls back
    to an intent-aware default (see below) when nothing scores."""
    scores = {a: _count_hits(normalized, phrases) for a, phrases in ANSWER_TYPE_INDICATORS.items()}
    top_type, top_score = max(scores.items(), key=lambda kv: kv[1])
    if top_score >= MIN_SCORE:
        return top_type
    # No answer_type indicator fired -- "procedure" is the closer default
    # for request_service (matches the LLM prompt's own template choice
    # in answer_composition.py, which only picks an action-specific
    # template for request_service), "other" is the safe generic default
    # everywhere else, matching ANSWER_TYPES' own catch-all purpose.
    return "procedure" if top_intent == "request_service" else "other"


def _derive_service(entities: list[dict]) -> str | None:
    """
    v1's rule engine never resolves `service` -- that's a separate layer
    there. v2's single LLM call resolves it together with intent/action/
    answer_type, so skipping that call without an alternative `service`
    source would only save part of the latency this whole feature exists
    for. The alternative: `entities` (computed by extract_entities BEFORE
    structured_intent.py runs, always) already tends to have a document/
    service-typed entity when one is real, and every entity here is
    already self-validating (a real substring of the message, per
    entity_extraction.py's own guarantee) -- no additional guardrail
    needed beyond what already produced it. Picks the longest text when
    more than one candidate exists, same "more complete span wins"
    tie-break entity_extraction.py's own _merge_entity already uses.
    """
    candidates = [e["text"] for e in entities if e.get("type") in ("document", "service")]
    if not candidates:
        return None
    return max(candidates, key=len)


def resolve_intent_fast(text: str, entities: list[dict]) -> FastPathResult:
    """
    Attempts a full intent/action/answer_type/service resolution without
    any LLM call. Returns `resolved=False` (with a reason, for
    logging/tuning) whenever there isn't enough unambiguous signal to
    commit -- the caller is expected to fall through to the LLM in that
    case, exactly as if this function didn't exist.
    """
    normalized = normalize_for_comparison(text)
    scores = {intent: _count_hits(normalized, phrases) for intent, phrases in INTENT_INDICATORS.items()}
    top_intent, top_score, runner_up_score = _top_two(scores, _INTENT_PRECEDENCE)

    if top_score < MIN_SCORE:
        return FastPathResult(resolved=False, abstain_reason="no_signal", scores=scores)
    if top_score - runner_up_score < MIN_MARGIN:
        return FastPathResult(resolved=False, abstain_reason="low_margin", scores=scores)

    service = _derive_service(entities)
    # Only request_service/question actually need `service`/`kb_match` to
    # compose a real answer (see answer_composition.py's own branching --
    # complaint never trusts kb_match regardless, "other" doesn't need a
    # service at all) -- gate commitment on having a real, non-LLM service
    # source specifically for the two intents where its absence would
    # matter, rather than blocking every intent on it.
    if top_intent in ("request_service", "question") and service is None:
        return FastPathResult(resolved=False, abstain_reason="no_service_entity", scores=scores)

    action = _resolve_action(normalized)
    answer_type = _resolve_answer_type(normalized, top_intent)
    return FastPathResult(
        resolved=True, intent=top_intent, action=action,
        answer_type=answer_type, service=service, scores=scores,
    )
