# Fix 007: template-only answer composition (step 5, kb_match case)

## What

Step 5 of the original pipeline design ("Answer composition") had never been
built -- every version of `gui.py` since v1 explicitly flagged this as the
missing piece, and this whole alpha effort deliberately deferred it until
extraction (steps 1-3) and KB lookup (step 4) were solid. New file
`answer_composition.py`, `compose_answer(record)`.

Only the `kb_match`-present case is handled. Deliberately: it's the case where
we have real, grounded data (a title and a real URL) to build a template
answer from with zero LLM calls -- same "rules where the vocabulary is closed"
approach as `date_rules.py`/`gazetteer.py`. When `kb_match` is `None`
(complaints, ambiguous questions, no confident KB match), `compose_answer`
returns `None` -- that's the genuinely harder case (needs either real content
this KB scrape doesn't have, or an LLM), left unbuilt on purpose so we can see
how often it actually comes up before deciding how to handle it.

## Design

Two template tiers, selected in this order:

1. **Action-specific** (`apply`/`renew`/`pay`/`check_status`) -- used only
   when `intent == "request_service"` and a real action was resolved. Gives
   an actionable tone ("here's how to apply for X").
2. **`answer_type`-based fallback** (`cost`/`deadline`/`requirements`/
   `contact`/`procedure`/`other`) -- used for everything else: `question`/
   `complaint`/`other` intents, or a `request_service` message whose action
   didn't resolve (`unknown`).

Every template names the real KB title and links the real URL -- none of them
invent a cost, deadline, or procedure, because the KB scrape only has `title`
and `url` per service (`description`/`keywords`/`category` are empty in
`data/heraklion_eservices.json`). This is the same reasoning as `fix-003`'s
guardrail on `service`, applied to the final answer text: better to point at
the real source than fabricate content we don't have.

Also wired into `run.py`: every logged record now includes an `answer` field
(the composed answer, or `null`), and the harness prints it under the JSON
when present. Logging it either way (not just when non-null) makes it
possible to see, from the eval log alone, how often a real answer could be
composed versus not -- useful evaluation data in itself.

## Evidence

| Message | intent/action/answer_type | kb_match | Answer |
|---|---|---|---|
| "Χρειάζομαι βεβαίωση μόνιμης κατοικίας...μέχρι αύριο." | request_service / apply / procedure | real match | action template: "Για να κάνετε αίτηση για «Βεβαίωση Μόνιμης Κατοικίας Δημότη Ηρακλείου», δείτε...: [url]" |
| "Πόσο κοστίζει η βεβαίωση μόνιμης κατοικίας;" | question / unknown / cost | real match (same service) | answer_type fallback correctly used instead of action template (action was unknown): "Για το κόστος της υπηρεσίας «...», δείτε...: [url]" |
| "Πόσο θα μου κοστίσει η σύνδεση φυσικού αερίου;" | question / unknown / cost | `None` (confirmed genuine gap, no such KB title) | `None` -- correctly deferred rather than composing something ungrounded |
| "Γεια σας" | other / unknown / other | `None` | `None` |

Both template-selection branches (action-specific and answer_type-fallback)
confirmed working on real pipeline output, not just unit-level template calls.

## What's still open

- The `kb_match is None` case is the majority of real traffic so far (most
  logged messages don't resolve to a confident KB match) -- this fix doesn't
  touch that case at all. Next real decision point: build a fallback there
  (LLM-generated freeform text, a generic "I couldn't find an exact match"
  message, or something else), once there's a sense of how often it's a
  genuine no-match versus a `service`/entity-extraction gap that should be
  fixed further upstream instead.
- Templates are static Greek phrasing, untested against native-speaker
  review for tone/naturalness -- functionally correct, not yet
  quality-reviewed as user-facing copy.
