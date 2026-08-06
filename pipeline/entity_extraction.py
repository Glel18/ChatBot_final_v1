"""
entity_extraction.py

Step 1 of the pipeline: pulls named "entities" (concrete facts) out of a
raw user message -- e.g. which document, date, or service is mentioned.

This step does NOT try to figure out what the user wants to do with those
facts -- that is structured_intent.py's job. Splitting it out like this
means each step only has one thing to get right: this step just has to
correctly spot and label facts, without needing to interpret verbs or intent.

Combines three sources, cheapest and most deterministic first:
  1. date_rules.find_dates -- regex + fixed weekday/relative-phrase list,
     no model call.
  2. gazetteer.find_service_entity -- matches the message against real KB
     service titles, no model call. Only fires when confident.
  3. LLM fallback -- for `location`/`other` (genuinely open-ended, no
     rule-based option), plus `document`/`service` IF the gazetteer found
     nothing (a real service phrased in a way that doesn't lexically
     resemble any KB title closely enough).

Steps 1-2 are self-validating by construction: a regex match or a KB-title
word-overlap run is always a real substring of the message, so there's
nothing to hallucinate. Only step 3's output passes through
_is_valid_entity, since an LLM is the only source here still capable of
inventing a span that isn't actually in the message.
"""

import json
import unicodedata

from date_rules import find_dates
from gazetteer import find_service_entity
from ollama_client import call_ollama

# Fixed, small vocabulary of entity types. Kept short deliberately -- add
# a new type only once real test messages show a category that's actually
# missing, rather than guessing upfront what might be needed.
ENTITY_TYPES = ["service", "document", "date", "location", "other"]


def extract_entities(text: str) -> list[dict]:
    """
    Takes a raw user message and returns the entities found in it, as a
    list like [{"text": "ταυτότητα", "type": "document"}, ...].

    Never raises: if the LLM call or its output is malformed, this still
    returns whatever the rule-based/gazetteer steps found rather than an
    empty list, since only step 3 depends on the network/model at all.
    """
    entities = find_dates(text)

    service_entity = find_service_entity(text)
    if service_entity:
        entities.append(service_entity)

    llm_entities = _extract_via_llm(text, already_found=entities)
    for entity in llm_entities:
        if _is_valid_entity(entity, text):
            entities = _merge_entity(entity, entities)

    return entities


def _merge_entity(new_entity: dict, existing: list[dict]) -> list[dict]:
    """
    Adds `new_entity` unless it overlaps (as a substring, in either
    direction) with something already found, in which case the longer,
    more complete span wins instead of keeping both.

    Testing showed a gazetteer fragment ("γέννησης") and a fuller
    LLM-sourced span for the same real-world thing ("πιστοποιητικό
    γέννησης") both surviving as separate entities -- an exact-match-only
    duplicate check missed this because the texts weren't identical and
    the types differed (service vs document). Substring overlap catches
    it regardless of type, since it's the underlying real-world referent
    that's duplicated, not the label.
    """
    new_norm = normalize_for_comparison(new_entity["text"])
    result = []
    keep_new = True
    for existing_entity in existing:
        existing_norm = normalize_for_comparison(existing_entity["text"])
        if new_norm == existing_norm or new_norm in existing_norm:
            result.append(existing_entity)  # existing is equal or more complete -- drop new
            keep_new = False
        elif existing_norm in new_norm:
            pass  # new is more complete -- drop the shorter existing one
        else:
            result.append(existing_entity)
    if keep_new:
        result.append(new_entity)
    return result


def _extract_via_llm(text: str, *, already_found: list[dict]) -> list[dict]:
    """
    Runs the LLM fallback and returns whatever entities it found, in the
    raw (not yet validated against the original message) shape it
    returned them in -- _is_valid_entity is what actually filters these
    before they reach the caller, not this function.

    Degrades to an empty list, never raises, on any malformed response:
    unparseable JSON, a JSON value that isn't an object, or an "entities"
    key that isn't a list. This is what lets extract_entities keep its
    "never raises" guarantee (see the module docstring) -- a bad LLM
    response just means step 3 contributed nothing this time, not a
    crash.
    """
    prompt = _build_prompt(text, already_found)
    raw_response = call_ollama(prompt, label="entity_extraction_llm")

    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError:
        return []

    entities = parsed.get("entities") if isinstance(parsed, dict) else None
    if not isinstance(entities, list):
        return []
    return entities


def _build_prompt(text: str, already_found: list[dict]) -> str:
    """
    The instruction sent to the LLM.

    `already_found` (from date_rules/gazetteer) is passed as a hint so the
    model focuses on what's actually left to find -- usually just
    `location`/`other` -- instead of re-deriving entities that are already
    resolved and risking a duplicate or a worse version of the same span.

    The few-shot examples are unchanged from before this rule/gazetteer
    layer was added (see notes/fix-001-entity-extraction-recall.md for why
    they're needed at all, and why one of them shows multiple entities in
    one message).
    """
    already_found_block = (
        json.dumps(already_found, ensure_ascii=False) if already_found else "none yet"
    )

    return f"""Extract ALL entities mentioned in the message below that aren't
already covered by the list below. A message can contain zero, one, or
several entities -- find every one that applies, not just the first or
most obvious.

Entities already found by other steps -- do NOT repeat these, only add
entities not already covered:
{already_found_block}

Allowed types: {", ".join(ENTITY_TYPES)}

Rules:
- Only extract text that appears word-for-word in the message (inflected
  Greek forms are fine, just copy the exact characters as they appear).
- Only use one of the allowed types listed above.
- If nothing relevant is found, return an empty list.

Examples:
Message: Θέλω να ανανεώσω το διαβατήριό μου.
Output: {{"entities": [{{"text": "διαβατήριό", "type": "document"}}]}}

Message: Θέλω να κλείσω ραντεβού για έκδοση πιστοποιητικού γέννησης την Τρίτη.
Output: {{"entities": [{{"text": "ραντεβού", "type": "service"}}, {{"text": "πιστοποιητικού γέννησης", "type": "document"}}, {{"text": "Τρίτη", "type": "date"}}]}}

Message: Γεια σας, τι κάνετε;
Output: {{"entities": []}}

Return a JSON object in exactly this shape:
{{"entities": [{{"text": "...", "type": "..."}}]}}

Message: {text}
"""


def normalize_for_comparison(text: str) -> str:
    """
    Strips accents and case, for comparison purposes only -- the original
    text is still what gets stored/returned. Needed because testing showed
    the model doesn't always reproduce Greek accents exactly (it once
    returned "αιτηση" for a message containing "αίτηση"); a plain
    substring check would wrongly reject that as hallucinated instead of
    recognizing it as the same word.

    Public (no leading underscore) because structured_intent.py reuses
    this for the same reason on the `service` field -- see the guardrail
    note on `_is_valid_service` there.
    """
    decomposed = unicodedata.normalize("NFD", text)
    without_accents = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return without_accents.lower()


def _is_valid_entity(entity, original_text: str) -> bool:
    """
    The guardrail for LLM-sourced entities only (see module docstring --
    date_rules/gazetteer entities are self-validating by construction and
    never reach this function). An entity is only kept if its `text`
    matches (accent- and case-insensitive) a substring of the original
    message, and its `type` is one of the allowed values. This is what
    actually prevents hallucinated spans from reaching structured_intent.py,
    enforced in code rather than trusted from the prompt alone.
    """
    if not isinstance(entity, dict):
        return False
    text = entity.get("text")
    entity_type = entity.get("type")
    if not isinstance(text, str) or not text.strip():
        return False
    if entity_type not in ENTITY_TYPES:
        return False
    return normalize_for_comparison(text) in normalize_for_comparison(original_text)
