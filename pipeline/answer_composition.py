"""
answer_composition.py

Step 5 of the pipeline: turns a resolved structured-intent record into an
actual Greek-language answer.

Branches, checked in this order (fix-008, revised after testing -- see
fix-009):
  1. intent == "complaint" -- ALWAYS the acknowledgment template,
     regardless of kb_match. Tested this against 6 real complaints:
     kb_match fired for 3 of them, and only 1 was actually the right
     page (street-lighting fault reports). The other 2 were topically
     adjacent but functionally wrong -- a billing DISPUTE matched to a
     "pay your bill online" page, a broken-bin REPORT matched to a
     "relocate your bin" page. Confidently pointing someone to the wrong
     process is worse than the generic fallback, so complaints never use
     kb_match at all, even when one exists. Score doesn't separate good
     from bad here either (the good match scored *lower* than one of the
     bad ones), so this isn't fixable by raising a threshold -- it needs
     to just not use kb_match for complaints, full stop.
  2. `kb_match` present -- template answer grounded in the real KB
     title/URL (fix-007). No LLM. (Not yet tested this rigorously for
     `question`/`request_service` intents the way complaints were --
     worth keeping in mind if similar wrong-purpose matches show up
     there too.)
  3. intent == "other" -- small talk / greetings, not a KB-matching
     problem. service is essentially always None here in practice, so
     this rarely competes with kb_match anyway.
  4. service is None -- we don't know what they want. The honest
     response is to ask, not to guess at an answer.
  5. service is set but no KB title matched confidently -- a real gap,
     either genuinely missing from this KB (confirmed cases exist, e.g.
     gas connection) or a near-miss the gazetteer couldn't confirm.

Every branch is still a plain template, no LLM call anywhere in this
file -- consistent with the rest of the pipeline (dates = rules,
service = gazetteer, answers = templates). Deliberately NOT using an LLM
to fill the "no exact match" case: that would reintroduce the exact
hallucination risk fix-003's guardrail exists to prevent, this time in
the final answer text instead of the `service` field. Ship the honest
version first, see from the log how often it's actually hit, decide
later whether it's worth the risk.

The one phone number used below (PHONE_FALLBACK) is copied from
gui.py, which already uses it for the same "contact the municipality
directly" purpose -- reused rather than invented for this file, same
principle as pointing to real KB URLs instead of fabricated content.
"""

from __future__ import annotations

PHONE_FALLBACK = "2813 409185"

# Used when intent is request_service and a real action is known --
# gives the reply an actionable tone ("here's how to renew X") rather
# than a purely informational one.
_ACTION_TEMPLATES = {
    "apply": "Για να κάνετε αίτηση για «{title}», δείτε την επίσημη σελίδα: {url}",
    "renew": "Για να ανανεώσετε «{title}», δείτε την επίσημη σελίδα: {url}",
    "pay": "Για να πληρώσετε σχετικά με «{title}», δείτε την επίσημη σελίδα: {url}",
    "check_status": (
        "Για να ελέγξετε την κατάσταση του αιτήματός σας για «{title}», "
        "δείτε: {url}"
    ),
    "cancel": "Για να ακυρώσετε «{title}», δείτε την επίσημη σελίδα: {url}",
    "schedule": "Για να κλείσετε ραντεβού σχετικά με «{title}», δείτε: {url}",
}

# Fallback, keyed by answer_type, used whenever intent isn't
# request_service, or the action is "unknown" -- covers question/
# complaint/other, and any request_service message where the action
# genuinely wasn't resolved (see notes/open-weakpoints.md #5, action
# vocabulary gaps).
_ANSWER_TYPE_TEMPLATES = {
    "cost": "Για το κόστος της υπηρεσίας «{title}», δείτε την επίσημη σελίδα: {url}",
    "deadline": "Για προθεσμίες σχετικά με «{title}», δείτε την επίσημη σελίδα: {url}",
    "requirements": (
        "Για τα δικαιολογητικά που χρειάζονται για «{title}», δείτε την "
        "επίσημη σελίδα: {url}"
    ),
    "contact": "Για στοιχεία επικοινωνίας σχετικά με «{title}», δείτε: {url}",
    "procedure": (
        "Για να δείτε πώς γίνεται η διαδικασία για «{title}», επισκεφθείτε: {url}"
    ),
    "other": "Σχετικά με «{title}», μπορείτε να βρείτε περισσότερες πληροφορίες εδώ: {url}",
}


def compose_answer(record: dict) -> dict:
    """
    Returns {"text": <Greek answer string>, "source": <label>}.

    Always produces something now -- before fix-008 this returned None
    whenever kb_match was missing; the branches below mean every record
    gets *some* answer. `source` says which branch produced it (kb_match
    / complaint_acknowledgment / small_talk / clarification_needed /
    no_kb_match), logged alongside the text so the eval log shows at a
    glance how messages are being handled without re-deriving it from
    intent/service/kb_match every time.

    intent == "complaint" is checked BEFORE kb_match, deliberately --
    see the module docstring for why (real testing showed kb_match
    producing confidently wrong-purpose answers for complaints 2 times
    out of 3 real matches).
    """
    intent = record.get("intent")
    if intent == "complaint":
        return {"text": _compose_complaint_ack(), "source": "complaint_acknowledgment"}

    kb_match = record.get("kb_match")
    if kb_match:
        return {"text": _compose_from_kb_match(record, kb_match), "source": "kb_match"}

    if intent == "other":
        return {"text": _compose_small_talk(), "source": "small_talk"}
    if record.get("service") is None:
        return {"text": _compose_clarification(record), "source": "clarification_needed"}
    return {"text": _compose_no_match(record), "source": "no_kb_match"}


def _compose_from_kb_match(record: dict, kb_match: dict) -> str:
    """
    Template choice: the action-specific template wins only when intent
    is request_service AND a real action was resolved (not "unknown") --
    that's the case where we can say something more specific than "here's
    information about X". Everything else falls back to the answer_type
    template, which is what the message was actually asking about
    regardless of intent.
    """
    title = kb_match["title"]
    url = kb_match["url"]

    action = record.get("action")
    if record.get("intent") == "request_service" and action in _ACTION_TEMPLATES:
        template = _ACTION_TEMPLATES[action]
    else:
        answer_type = record.get("answer_type", "other")
        template = _ANSWER_TYPE_TEMPLATES.get(answer_type, _ANSWER_TYPE_TEMPLATES["other"])

    return template.format(title=title, url=url)


def _compose_complaint_ack() -> str:
    """Fixed acknowledgment for every complaint, regardless of kb_match -- see
    the module docstring for why complaints never use kb_match at all."""
    return (
        "Καταγράψαμε το παράπονό σας. Για άμεση εξέταση, επικοινωνήστε με "
        f"τον Δήμο Ηρακλείου στο {PHONE_FALLBACK}."
    )


def _compose_small_talk() -> str:
    """Fixed greeting reply for intent == "other" -- no kb_match to ground
    against, and none needed for greetings/small talk."""
    return "Είμαι εδώ για να σας βοηθήσω με θέματα του Δήμου Ηρακλείου. Πώς μπορώ να βοηθήσω;"


def _compose_clarification(record: dict) -> str:
    """
    References a found entity when there is one, even though `service`
    itself never resolved -- e.g. a document/service entity that was too
    generic to validate as a real service name (see the "κοινωνικό
    επίδομα" -> "αίτηση" case in open-weakpoints.md). Makes the question
    more specific than a bare "what do you mean?" when we have something,
    even partial, to point back at.
    """
    entities = record.get("entities", [])
    doc_or_service = [e for e in entities if e.get("type") in ("document", "service")]
    if doc_or_service:
        mentioned = doc_or_service[0]["text"]
        return (
            f"Καταλαβαίνω ότι αναφέρεστε σε «{mentioned}», αλλά δεν είμαι "
            "σίγουρος/η ποια ακριβώς υπηρεσία του Δήμου εννοείτε. Μπορείτε "
            "να διευκρινίσετε;"
        )
    return (
        "Δεν είμαι σίγουρος/η ποια υπηρεσία του Δήμου εννοείτε. Μπορείτε "
        "να διευκρινίσετε τι ακριβώς χρειάζεστε;"
    )


def _compose_no_match(record: dict) -> str:
    """Branch 5: service was resolved but no KB title cleared the confidence
    threshold -- either a genuine gap in the KB (e.g. gas connection, see
    fix-006) or a near-miss the gazetteer couldn't confirm. Same honest
    "here's the phone number" answer either way, since this function has
    no way to tell those two cases apart -- see backlog.md's
    ask-for-clarification entry for the idea of eventually splitting them."""
    service = record["service"]
    return (
        f"Δεν βρήκα ακριβή αντιστοιχία για «{service}» στις υπηρεσίες μας. "
        f"Παρακαλώ επικοινωνήστε με τον Δήμο Ηρακλείου στο {PHONE_FALLBACK} "
        "για περισσότερες πληροφορίες."
    )
