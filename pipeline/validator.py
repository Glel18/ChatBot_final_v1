"""
validator.py

Centralizes the invariants a resolved structured-intent record is supposed
to satisfy -- required fields, allowed-value enums, well-formed/typed/
deduplicated entities, and cross-field consistency (e.g. `service` can't
be null while a document/service entity is present). Loosely modeled on
v1's `structured_intent/validator.py`, but NOT a port: v1 validates a
multi-`requests` envelope with `needs_clarification`/`search_terms` that
v2's schema doesn't have. This is a fresh module shaped around v2's actual
flat record (input/entities/intent/service/action/answer_type/constraints/
kb_match).

Deliberately NOT ported from v1: the "answer_type must match a fixed
mapping for this intent" rule. v1 folds "what information does the user
want" into `intent` itself (find_cost, find_deadline, ...), so a 1:1
intent -> answer_type mapping is a real, load-bearing invariant there. v2
keeps `intent` coarse (request_service/question/complaint/other) and lets
`request_service`/`question` legitimately pair with any of the 6
`answer_type` values -- there's no real fixed mapping in v2's actual data
to enforce, and inventing one now would risk flagging perfectly correct
records as invalid.

Two calling conventions, used deliberately differently by different
callers (see structured_intent.py):
  - `validate_structured_intent` -- never raises, returns a list of
    violation strings (empty if none). Used on the existing LLM path as a
    soft, logged-for-review check -- `_normalize` already coerces every
    field to a safe default before this runs, so this should return []
    there by construction; it's defense-in-depth, not a new gate on
    anything currently reachable through that path.
  - `validate_or_raise` -- same checks, raises StructuredIntentValidationError
    on any violation. Used as a hard gate for the new rule-based fast
    path's candidate record, one call-frame before it would ever be
    trusted -- safe to be strict there specifically because the caller
    catches it and treats a failure exactly like an abstain (fall through
    to the LLM), so it never actually surfaces to a user; it only costs
    that one message's latency win.
"""

from __future__ import annotations

from entity_extraction import ENTITY_TYPES, normalize_for_comparison
from taxonomy import ACTIONS, ANSWER_TYPES, INTENTS

_REQUIRED_FIELDS = ("input", "entities", "intent", "service", "action", "answer_type", "constraints")


class StructuredIntentValidationError(ValueError):
    """Raised by validate_or_raise when a record violates an invariant."""


def validate_structured_intent(record: dict, entities: list[dict]) -> list[str]:
    """
    Checks `record` against the invariants listed in the module docstring.
    Never raises -- returns a list of human-readable violation strings,
    empty if the record is clean. `entities` is passed separately (not
    just read off record["entities"]) so callers building a candidate
    record can validate against the real entity list even before every
    field of `record` is fully assembled.

    Allowed-vocabulary checks use taxonomy.py's INTENTS/ACTIONS/ANSWER_TYPES
    directly -- both this module and structured_intent.py import from
    taxonomy.py (a leaf module, nothing imports back from it), rather than
    this module importing structured_intent.py directly, which would be a
    circular import (structured_intent.py needs to import THIS module to
    call validate_or_raise on the fast path's candidate record).
    """
    errors: list[str] = []

    for field in _REQUIRED_FIELDS:
        if field not in record:
            errors.append(f"missing field: {field}")

    if record.get("intent") not in INTENTS:
        errors.append(f"intent not in allowed vocabulary: {record.get('intent')!r}")
    if record.get("action") not in ACTIONS:
        errors.append(f"action not in allowed vocabulary: {record.get('action')!r}")
    if record.get("answer_type") not in ANSWER_TYPES:
        errors.append(f"answer_type not in allowed vocabulary: {record.get('answer_type')!r}")

    service = record.get("service")
    if service is not None and (not isinstance(service, str) or not service.strip()):
        errors.append("service must be a non-empty string or null")

    seen_entities: set[tuple[str, str]] = set()
    for entity in record.get("entities", []):
        if not isinstance(entity, dict) or "text" not in entity or "type" not in entity:
            errors.append(f"malformed entity: {entity!r}")
            continue
        if entity["type"] not in ENTITY_TYPES:
            errors.append(f"entity has unsupported type: {entity!r}")
        key = (normalize_for_comparison(str(entity["text"])), entity["type"])
        if key in seen_entities:
            errors.append(f"duplicate entity: {entity!r}")
        seen_entities.add(key)

    constraints = record.get("constraints")
    if not isinstance(constraints, list) or not all(isinstance(c, str) for c in constraints):
        errors.append("constraints must be a list of strings")

    # Cross-field: mirrors the relationship _entities_agree_with_service
    # already flags in structured_intent.py, phrased here as a discrete
    # invariant rather than a soft heuristic -- kept as an ADDITIONAL
    # check, not a replacement for entity_service_consistent (see module
    # docstring on the two calling conventions for why this stays
    # non-fatal on the existing LLM path).
    doc_or_service_entities = [e for e in entities if e.get("type") in ("document", "service")]
    if service is None and doc_or_service_entities:
        errors.append("service is null but a document/service entity is present")

    return errors


def validate_or_raise(record: dict, entities: list[dict]) -> None:
    """Same checks as validate_structured_intent, raised instead of returned."""
    errors = validate_structured_intent(record, entities)
    if errors:
        raise StructuredIntentValidationError("; ".join(errors))
