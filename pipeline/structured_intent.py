"""
structured_intent.py

Step 2 of the pipeline: takes the raw message AND the entities already
found by entity_extraction.py, and resolves what the user actually wants
done -- intent, which service, what action, what kind of answer they need.

This needs the raw sentence again, not just the entity list, because
intent lives in sentence structure (verbs, question words), which entity
extraction deliberately ignores. Two messages can share identical entities
but need completely different answers -- e.g. "when does my ID expire" vs
"I want to renew my ID" both mention the same document, but one is a
status question and the other is a service request.
"""

import json

import intent_rules
import validator
from entity_extraction import extract_entities, normalize_for_comparison
from gazetteer import find_kb_match
from ollama_client import call_ollama
from taxonomy import ACTIONS, ANSWER_TYPES, INTENTS

# One-line rule per intent, not an example. Testing showed real messages
# getting misclassified when the prompt only listed these as bare words
# (a complaint landed as "question", a cost question landed as "other").
# A short definition fixed both, plus a third inconsistent case, without
# adding a single example -- a definition teaches the general rule, an
# example only teaches that one sentence shape. Prefer adding a definition
# here over adding an example when a category boundary is the problem;
# only reach for an example if the model is missing something no rule can
# capture in one sentence.
INTENT_DEFINITIONS = {
    "request_service": (
        'the user wants the municipality to DO or PROCESS something for them '
        'right now -- apply, renew, pay, cancel, get a document issued. '
        'Usually phrased as a statement of desire/intent ("I want to...", '
        '"I need to..."), not a question.'
    ),
    "question": (
        "the user is asking for INFORMATION only -- cost, deadline, "
        "requirements, location, opening hours, status -- without asking "
        "the municipality to act on their behalf right now. Usually phrased "
        "as a question."
    ),
    "complaint": (
        "the user is reporting a problem, delay, error, or expressing "
        "dissatisfaction about something that already happened or should "
        "have happened."
    ),
    "other": "greetings, small talk, or anything that doesn't fit the categories above.",
}


def resolve_structured_intent(text: str) -> dict:
    """
    Full step-1+2 pipeline for one user message. Returns a single flat
    dict matching the alpha evaluation schema: input, entities, then the
    resolved intent/service/action/answer_type/constraints.

    Tries the rule-based fast path first (intent_rules.py -- no LLM call,
    no I/O): a real fraction of messages have unambiguous enough signal to
    resolve deterministically, and skipping structured_intent_llm for
    those is most of this step's latency (see notes/fix-016 for the
    measured evidence). Falls through to the unchanged LLM path whenever
    the fast path abstains (not enough signal, a tied signal, or no
    non-LLM way to resolve `service`) -- from the caller's perspective
    nothing about the LLM path's behavior changes.
    """
    entities = extract_entities(text)

    fast_result = _try_fast_path(text, entities)
    if fast_result is not None:
        return fast_result

    prompt = _build_prompt(text, entities)
    raw_response = call_ollama(prompt, label="structured_intent_llm")

    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError:
        parsed = {}

    if not isinstance(parsed, dict):
        parsed = {}

    return _normalize(text, entities, parsed)


def _try_fast_path(text: str, entities: list[dict]) -> dict | None:
    """
    Attempts to resolve `text` via intent_rules.resolve_intent_fast and,
    if it committed, validates the candidate record before ever returning
    it -- a validation failure here is treated exactly like an abstain
    (fall through to the LLM), never surfaced as an error, so it only ever
    costs that one message's latency win, not correctness. This is the one
    place validator.validate_or_raise is used as a hard gate rather than
    the soft logged-flag validator.py uses on the LLM path below (see
    validator.py's module docstring for why the split is deliberate).
    """
    result = intent_rules.resolve_intent_fast(text, entities)
    if not result.resolved:
        return None

    candidate = _finalize(
        text, entities,
        intent=result.intent, action=result.action, answer_type=result.answer_type,
        service=result.service, constraints=[], source="rule_fast_path",
    )
    try:
        validator.validate_or_raise(candidate, entities)
    except validator.StructuredIntentValidationError:
        return None
    return candidate


def _build_prompt(text: str, entities: list[dict]) -> str:
    """
    Includes both the raw sentence (needed to resolve intent/action) and
    the entities already found (so the model treats them as given facts
    instead of re-deriving -- and possibly disagreeing with -- them).
    """
    entities_block = json.dumps(entities, ensure_ascii=False) if entities else "none found"
    intent_defs = "\n".join(f"- {name}: {rule}" for name, rule in INTENT_DEFINITIONS.items())

    return f"""You are resolving what a user wants from a Greek municipal-services chatbot.

Entities already found in this message -- treat these as given, do not
contradict or re-derive them:
{entities_block}

Intent definitions -- choose exactly one:
{intent_defs}

Allowed action values: {", ".join(ACTIONS)}
Allowed answer_type values: {", ".join(ANSWER_TYPES)}

Return a JSON object in exactly this shape:
{{"intent": "...", "service": "... or null", "action": "...", "answer_type": "...", "constraints": ["..."]}}

Message: {text}
"""


def _is_valid_service(service, original_text: str) -> bool:
    """
    Guardrail for `service`, same idea as `_is_valid_entity` in
    entity_extraction.py. Unlike entities, this field had NO check at all
    until now, and testing surfaced it returning values with no
    relationship to the input whatsoever: an English translation
    ("marriage_license"), the entity *type* instead of a name
    ("document"), a bare English noun ("payment"), and a Greeklish
    transliteration ("pistopoiitiko genisi") -- see notes/open-weakpoints.md.

    There's no KB lookup yet to check `service` against real municipal
    service names (that's a later pipeline step), so the cheapest real
    check available right now is the same one entities already use:
    require it to actually appear in the message. This won't catch a
    *wrong but real* span (e.g. the model picking the wrong phrase from
    the message), only a fully invented one -- which is exactly the
    failure mode observed so far.
    """
    if not isinstance(service, str) or not service.strip():
        return False
    return normalize_for_comparison(service) in normalize_for_comparison(original_text)


def _entities_agree_with_service(service: str | None, entities: list[dict]) -> bool:
    """
    Cheap, code-only consistency check between the resolved `service` and
    the document/service-typed entities entity_extraction.py already
    found -- NOT a second LLM opinion re-deriving and reconciling
    entities. That alternative was considered and deliberately rejected:
    it reintroduces the exact "two independently-produced signals that
    can disagree" problem this pipeline was built to avoid (see the
    module docstring and notes/fix-002 -- entities are passed into the
    prompt above as trusted hints specifically so nothing downstream
    re-derives and possibly contradicts them). A second LLM call also
    isn't guaranteed to catch anything the first one missed, since it's
    the same model with the same blind spots, and it would double the
    latency this pipeline already spends per message.

    This is the lighter alternative: a flag on the logged record for
    human review during evaluation, not automated resolution. Mirrors a
    rule v1's validator already enforced (a `municipal_service` entity
    without a matching `service` value is a real inconsistency worth
    catching), extended to also flag the reverse case.
    """
    doc_or_service_entities = [e for e in entities if e.get("type") in ("document", "service")]

    if service is None:
        # A document/service entity was found, but the intent layer never
        # committed to a `service` value at all -- worth a second look.
        return len(doc_or_service_entities) == 0

    if not doc_or_service_entities:
        # A service was named with no supporting entity for it. Not
        # impossible on its own (the LLM can name a real service in
        # freeform text that entity_extraction.py separately missed as
        # an entity), but worth flagging rather than assuming it's fine.
        return False

    service_norm = normalize_for_comparison(service)
    return any(
        service_norm in normalize_for_comparison(e["text"])
        or normalize_for_comparison(e["text"]) in service_norm
        for e in doc_or_service_entities
    )


def _normalize(text: str, entities: list[dict], parsed: dict) -> dict:
    """
    Builds the final record for the LLM path. Any field the LLM call
    failed to produce, or produced outside the allowed vocabulary, falls
    back to a safe default -- so a bad LLM response degrades gracefully
    instead of crashing the run or silently accepting an invented
    category. Thin wrapper around _finalize (shared with the fast path)
    now -- this function's only remaining job is pulling fields out of
    `parsed` and validating `service`.
    """
    intent = parsed.get("intent")
    action = parsed.get("action")
    answer_type = parsed.get("answer_type")
    constraints = parsed.get("constraints")
    service = parsed.get("service")
    service = service if _is_valid_service(service, text) else None

    return _finalize(
        text, entities,
        intent=intent, action=action, answer_type=answer_type,
        service=service, constraints=constraints, source="llm",
    )


def _finalize(
    text: str, entities: list[dict], *,
    intent, action, answer_type, service, constraints, source: str,
) -> dict:
    """
    Shared tail for both the fast path and the LLM path: KB lookup +
    final record assembly, coercing every field to a safe default the
    same way regardless of which path produced it. Factored out so the
    two paths can't quietly drift out of sync with each other -- same
    reasoning run.py's run_and_log was de-duplicated out of
    run_full_eval.py for.

    `intent_source` records which path produced this record ("llm" or
    "rule_fast_path") -- mirrors the `answer_source` convention
    answer_composition.py/run.py already use, so the fast path's real hit
    rate and latency delta are directly visible in eval_log.jsonl, not
    just claimed. `validation_errors` is only attached on the LLM path:
    the fast path's candidate already passed validator.validate_or_raise
    as a hard gate before reaching here (see _try_fast_path), so
    re-running the soft check on it would be redundant.
    """
    service = service if isinstance(service, str) and service.strip() else None

    # Step 4 of the pipeline: look up the real KB record for the
    # resolved `service`, not the raw message -- per the original design,
    # this is meant to be seeded by the already-narrowed service field,
    # not a fresh full-text search over the whole sentence. No lookup at
    # all if service is None: nothing to seed the search with, and
    # matching the raw message instead would just re-invite the
    # attractor-title false positives find_service_entity already had to
    # guard against during entity extraction (see fix-004).
    kb_match = find_kb_match(service) if service else None

    record = {
        "input": text,
        "entities": entities,
        "intent": intent if intent in INTENTS else "other",
        "service": service,
        "action": action if action in ACTIONS else "unknown",
        "answer_type": answer_type if answer_type in ANSWER_TYPES else "other",
        "constraints": constraints if isinstance(constraints, list) else [],
        "entity_service_consistent": _entities_agree_with_service(service, entities),
        "kb_match": kb_match,
        "intent_source": source,
    }
    if source != "rule_fast_path":
        record["validation_errors"] = validator.validate_structured_intent(record, entities)
    return record
