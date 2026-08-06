# Fix 014: scale best_match's word-overlap requirement to what the title can offer

## Why

Found while investigating a finding from the 2026-08-06 eval run
(`pipeline/logs/eval_summary_2026-08-06.md`): "Πόσο κοστίζει η χορήγηση
άδειας γάμου;" (marriage license granting cost) came back `kb_match: None`.
The eval summary's first-pass diagnosis called this a fix-013 false
negative -- assumed "χορήγηση άδειας γάμου" was itself a real KB title,
just wrongly blocked by the 2-word gate.

**That diagnosis was wrong, corrected before this fix was written, not
after.** Re-testing directly against the gazetteer (not just re-running the
one message) showed there is no KB title called "Χορήγηση Άδειας Γάμου" --
the real KB splits marriage licenses into "για Έλληνες Πολίτες" (Greek
citizens) and "για Αλλοδαπούς" (foreigners) variants, and the top 5
candidates for the bare query are closely clustered (0.339-0.407), with no
clear winner. The query is genuinely ambiguous between several real
titles; declining to guess there isn't a bug, it's the intended
conservative behavior. `eval_summary_2026-08-06.md` has been corrected in
place to reflect this rather than left wrong.

**But the deeper check that correction required surfaced a real bug.**
Scanning all 164 KB titles for how many collapse to 1 or 0 real content
words after `_strip_generic_terms` found 7:

- Αίτημα για οδοκαθαρισμό (street cleaning request)
- Κατασχέσεις (seizures/confiscations)
- Αίτηση για Εργοθεραπεία (occupational therapy)
- Αίτηση για Φυσικοθεραπεία (physiotherapy)
- Αίτηση για Ιατρονοσηλευτική (home nursing care)
- Βεβαίωση Υψομέτρου (elevation certificate)
- Χορήγηση Βεβαίωσης Χρήσης Γης (land-use certificate)

`fix-013`'s gate required 2 shared word-stems between query and title,
unconditionally. For these 7, the title itself can never contribute more
than 1 stem -- so the requirement was mathematically impossible to satisfy,
for ANY query, no matter how well-phrased. Confirmed, not just reasoned
about: queried each of the 7 with its own exact title text (the best
possible case) and all 7 still returned `None`. These services had been
completely unreachable through `find_kb_match` since `fix-013` shipped.

## Fix

`Gazetteer.best_match` (`gazetteer.py`) no longer requires a flat 2 shared
stems. It now requires `min(2, len(title_stems))` -- the title's own real
content-word count, capped at 2. A title with 2+ real words keeps the full
fix-013 protection unchanged (still needs 2 shared words, same
false-positive protection as before). A title with exactly 1 real word
(the 7 above) now only needs that 1 word to genuinely match -- restoring
matchability without reopening the coincidental-single-word-collision
problem fix-013 fixed, since these titles only ever had 1 real word to
offer in the first place; there was never a second word available to
provide false corroboration. A title with 0 real content words (none
currently in the KB) is rejected outright rather than let the requirement
hit 0 and accept anything -- explicit code path, not just an artifact of
the `min()` math, so it can't silently start matching everything if the KB
ever gains a fully-generic title later.

## Evidence

**The 7 previously-unreachable titles, queried with their own exact text:**

| Title | Before | After |
|---|---|---|
| Αίτημα για οδοκαθαρισμό | `None` | matches itself |
| Κατασχέσεις | `None` | matches itself |
| Αίτηση για Εργοθεραπεία | `None` | matches itself |
| Αίτηση για Φυσικοθεραπεία | `None` | matches itself |
| Αίτηση για Ιατρονοσηλευτική | `None` | matches itself |
| Βεβαίωση Υψομέτρου | `None` | matches itself |
| Χορήγηση Βεβαίωσης Χρήσης Γης | `None` | matches itself |

**No regression on titles with 2+ real words** (unaffected by this
change -- `required_overlap` is still 2 for all of them): re-ran
`fix-013`'s direct regression suite (residence certificate, both street
lighting phrasings, both bin-relocation phrasings, recycling bin question,
excavation permit, passport, water bill, bare "ραντεβού", gas connection,
water network expansion, transfer of remains) -- all still correct.

**No regression on the PDF-audit bad-match list**: re-ran all 15 confirmed
wrong-purpose-match queries from `fix-012`/`fix-013` -- all still correctly
rejected.

**The one documented `fix-013` residual case is unchanged, as expected**:
"τέλη καθαριότητας κοιμητηρίων" still matches "ΤΑΠ - Τέλη Φωτισμού και
Καθαριότητας" (score 0.658) -- that title has 2+ real words, so this
fix doesn't touch it. Still an open, documented limitation (`fix-013`,
`open-weakpoints.md` #9), not something this fix was meant to address.

## What this doesn't fix, and why that's OK

The marriage-license-granting case that started this investigation is
still `None`, correctly -- it was never actually broken. A bare
"χορήγηση άδειας γάμου" query genuinely can't be resolved to one specific
title without more context (Greek citizen or foreigner?); the honest
answer is the clarification template, not a guess. No change made for
this case, since no bug was found there once tested properly.
