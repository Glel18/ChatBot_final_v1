"""
date_rules.py

Pure rule-based date-entity extraction: regex for absolute dates, a fixed
list for weekday names and common relative-date phrases. No LLM call.

Why rules fit this entity type specifically, unlike document/service
names: Greek has exactly 7 weekday names and a small, genuinely closed
set of relative-date phrases (αύριο, σήμερα, ...) -- there's no long tail
of novel phrasing to miss the way there is for service names. Testing
already showed the LLM being inconsistent here purely from model
variance: it missed "Σάββατο" as a date in one message but caught
"Δευτέρα" in another, same entity type, no real difference in difficulty.
A fixed list doesn't have that variance -- if a weekday name is in the
message, it's found, every time, deterministically.
"""

import re

WEEKDAYS = [
    "Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη",
    "Παρασκευή", "Σάββατο", "Κυριακή",
]

RELATIVE_DATE_PHRASES = [
    "σήμερα", "αύριο", "μεθαύριο", "χθες", "προχθές",
    "την επόμενη εβδομάδα", "τον επόμενο μήνα",
]

# DD/MM, DD/MM/YY, DD/MM/YYYY, and the same with '-' or '.' separators.
_ABSOLUTE_DATE_PATTERN = re.compile(r"\b\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?\b")


def find_dates(text: str) -> list[dict]:
    """
    Scans `text` for date-like substrings using the fixed lists above and
    the absolute-date regex -- no model call. Returns entities in the
    same shape the rest of the pipeline expects:
    [{"text": "...", "type": "date"}, ...].

    Word-boundary matching (\\b...\\b), not plain substring containment,
    so e.g. "Σάββατο" doesn't false-match inside an unrelated longer word.
    """
    found = []
    seen_spans: set[str] = set()

    for phrase in WEEKDAYS + RELATIVE_DATE_PHRASES:
        pattern = r"\b" + re.escape(phrase) + r"\b"
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match and match.group() not in seen_spans:
            found.append({"text": match.group(), "type": "date"})
            seen_spans.add(match.group())

    for match in _ABSOLUTE_DATE_PATTERN.finditer(text):
        if match.group() not in seen_spans:
            found.append({"text": match.group(), "type": "date"})
            seen_spans.add(match.group())

    return found
