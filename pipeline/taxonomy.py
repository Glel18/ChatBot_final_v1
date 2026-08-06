"""
taxonomy.py

The three closed vocabularies structured_intent.py resolves a message
into. Pulled out into their own module (not defined in structured_intent.py
as before) because a second and third consumer showed up at once --
validator.py needs to check a record's intent/action/answer_type against
these, and intent_rules.py needs the same vocab as its indicator-phrase
dict keys -- and both of those modules are imported BY structured_intent.py
(for the fast-path/validation wiring), so structured_intent.py owning the
vocab itself would make either import a cycle. A small shared module both
sides can import from, with nothing importing back from it, is the
standard fix -- same principle as pulling date-matching out of
entity_extraction.py into date_rules.py.

INTENT_DEFINITIONS stays in structured_intent.py, not here -- it's
prompt-engineering text for the LLM call specifically, not a vocabulary
other modules need.
"""

INTENTS = ["request_service", "question", "complaint", "other"]
# "cancel" and "schedule" added after real messages needed them and fell
# back to "unknown" -- see notes/fix-011 and notes/open-weakpoints.md #5
# (the schedule/cancel misclassification is still open on the LLM path).
ACTIONS = ["apply", "renew", "check_status", "pay", "cancel", "schedule", "unknown"]
ANSWER_TYPES = ["procedure", "cost", "deadline", "requirements", "contact", "other"]
