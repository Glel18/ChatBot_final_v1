# Fix 010: strip generic administrative words from gazetteer matching

## Why

`open-weakpoints.md` #9: `kb_match` was producing confidently wrong-purpose
matches outside complaints too -- "άδεια εκσκαφής" (excavation permit) matched
"Άδεια Πολιτικού Γάμου για Αλλοδαπούς" (marriage license for foreigners,
0.317), "έκδοση διαβατηρίου" (passport issuance cost) matched "Έκδοση
δημοτικής ενημερότητας" (municipal tax clearance issuance, 0.319). Checked
whether a stricter score threshold would fix it (`tried-and-failed.md`) --
it wouldn't, bad and good matches were interleaved across the whole score
range.

## Diagnosis

Computed real word frequency across all 167 KB titles rather than guessing
what might be "too generic." Top of the list: χορήγηση/granting (25 titles),
αίτηση/application (20), αδειας/permit (15), έκδοση/issuance (9),
βεβαίωση/certificate (9), δήλωση/declaration (8). Both bad matches found so
far shared *only* one of these words with their wrong match -- these describe
the bureaucratic PROCESS (granting, issuing, applying), not what the service
is actually about, so two completely unrelated services can share heavy
lexical overlap through them alone.

## Fix

New `_strip_generic_terms` in `gazetteer.py`: drops any word matching one of
7 stems (covers inflected forms: αδει- catches άδεια/αδειας/αδειων/αδειες)
from the text used for MATCHING/SCORING only. Applied to both sides
(KB titles, once, at index build time; every query, in `best_match`) so the
comparison stays apples-to-apples. Does NOT touch `find_service_entity`'s
span extraction, which still needs the full, untouched title to find real
entity spans in the message -- stripping only changes which title gets
picked as the match, not what text gets returned once one is picked.

## Evidence

Re-tested all 6 known cases (2 good, 4 bad) directly through `find_kb_match`:

| Query | Before | After |
|---|---|---|
| residence certificate (good) | 0.774, correct | 0.734, still correct |
| street lighting fault (good) | 0.373, correct | 0.374, still correct |
| passport issuance cost (bad) | 0.319, wrong (tax clearance) | **`null` -- fixed** |
| excavation permit (bad) | 0.317, wrong (marriage license) | **`null` -- fixed** |
| water bill dispute (bad) | 0.324, wrong (pay bill online) | 0.323, still wrong |
| broken recycling bin (bad) | 0.420, wrong (relocate bin) | 0.427, still wrong |

Both good matches survived unaffected (scores barely moved). Both
generic-word-caused bad matches are gone. The 2 remaining bad matches are
untouched, and are a genuinely different failure mode (see below) --
stripping generic process words can't fix a case that has no generic process
word in common to begin with.

## What's not fixed, and why that's currently OK

Water-bill and recycling-bin still match wrong-purpose titles, because they
share real content words ("λογαριασμός"/bill, "κάδος"/bin) with a KB entry
that's topically right but purpose-wrong (this KB may simply not have a
"dispute your bill" or "report a broken bin" service, only "pay" or
"relocate" -- closer to the confirmed gas-connection gap than to a matching
bug). A score margin check wouldn't help here either -- checked, and since
each is likely the *only* KB title on that topic, it wins by a wide margin
over everything else, not a coincidental near-tie.

Both remaining bad cases are `complaint`-intent messages, already fully
bypassed by `fix-009`'s complaint-first routing -- they never reach this
matching logic in the real pipeline. So this is masked for complaints
specifically, not actually fixed at the source. If a similar
topically-right-but-purpose-wrong pattern ever shows up on a
`question`/`request_service` message, it would still be a live risk --
worth retesting those intents specifically if this keeps recurring.

## End-to-end confirmation

The evidence above was `find_kb_match` called directly, bypassing
`structured_intent.py`'s LLM step. Re-ran the same 8-message
question/request_service batch that originally surfaced this issue through
the full `resolve_structured_intent` pipeline (real LLM calls, not a direct
function call) to make sure the fix holds once the LLM-resolved `service`
string is what's actually feeding the gazetteer, not a hand-picked query
string. Both previously-bad cases (passport issuance, excavation permit) came
back `kb_match: null`; all 6 previously-safe cases were unchanged. 0 bad
matches this run, versus 2 before -- confirmed, not just plausible from the
isolated test.
