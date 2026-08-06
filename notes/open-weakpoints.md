# Open weak points

Known issues found through batch testing that haven't been fixed yet. Updated as
new batches surface new gaps; an item moves out of here and into its own
`fix-NNN-*.md` once addressed.

## 1. No entity type covers fees/payments

"Πρέπει να πληρώσω τα δημοτικά τέλη μέχρι πότε;" (by when must I pay municipal
fees?) extracted zero entities. `ENTITY_TYPES` is currently
`service, document, date, location, other` -- none of these cleanly fits
"δημοτικά τέλη" (municipal fees). v1's schema had a `payment` entity type that we
dropped when simplifying; this is the kind of real-data signal that was supposed
to bring a type back, per our own design rule ("add a type only once real
messages show it's actually missing").

**Status:** sharpened, not just recurring. The phrase-specific theory turned out
to be wrong: "Θέλω να πληρώσω τα δημοτικά τέλη για το σπίτι μου." (statement
form) caught `δημοτικά τέλη` correctly. But "Πόσο είναι ο δημοτικός φόρος
ακίνητης περιουσίας;" -- a *different* fee phrase, in question form -- missed
it again. So the real pattern looks like: **fee/tax entities get missed
specifically when the message is a cost question**, regardless of the exact
phrase, and get caught when the message is a statement/request. 2/2 question-form
misses, 1/1 statement-form catch so far -- worth testing a couple more cost
questions about fees specifically to confirm before touching the prompt.

## 2. Multi-entity recall is inconsistent

The fix in `fix-001` (adding a multi-entity few-shot example) helped but didn't
fully close this:

- "Καλησπέρα, είστε ανοιχτά το Σάββατο;" caught `Καλησπέρα` but missed `Σάββατο`
  (Saturday) as a `date`.
- "Δεν λειτουργεί ο δημοτικός φωτισμός στην γειτονιά μου εδώ και μια εβδομάδα."
  caught the `service` but missed `γειτονιά μου` (location) and `μια εβδομάδα`
  (a week, date/duration).

**Status:** the `date` half of this is now resolved by `fix-004` -- weekday
names and relative-date phrases are matched by a fixed rule list
(`date_rules.py`), not the LLM, so "Σάββατο"/"αύριο"-style misses can't recur by
construction (deterministic lookup, not model variance). The remaining risk is
`document`/`service` entities still occasionally getting missed or fragmented on
the LLM fallback path -- that part is unchanged by `fix-004` and still worth
watching.

## 3. Greeting-prefixed real questions get misclassified as `other`

"Καλησπέρα, είστε ανοιχτά το Σάββατο;" is a genuine opening-hours question (fits
the `question` definition: asking for information), but resolved to `other` --
looked like the greeting at the start of the message was dominating the
classification over the substantive question that follows it.

**Status:** mostly disconfirmed. Tested 2 more greeting+question combos:
"Καλημέρα, πόσο κοστίζει η άδεια γάμου;" -> correctly `question`, and "Γεια σας,
θέλω να μάθω τις ώρες λειτουργίας του δημαρχείου." -> also correctly `question`
(and notably didn't get pulled toward `request_service` despite starting with
"θέλω να", the same phrasing our request_service examples use -- it correctly
read "θέλω να μάθω" as wanting *information*, not wanting an action performed).
So "greetings dominate" doesn't hold up as a general rule -- 2 of 3 tested cases
were fine. The original failing case might be about "ανοιχτά" (open/closed,
yes/no framing) specifically rather than greetings. Not chasing this further
until it recurs with a clearer pattern.

**Not fixed by `fix-016`, but worth noting why.** `intent_rules.py`'s
scoring correctly ranks `question` above `other` for both known cases here
(checked directly against `scores`, not inferred) -- the phrase-length
weighting mechanism structurally favors real content signal over a bare
greeting, without a special case. But both cases also abstain on
`no_service_entity` (a generic hours/info question has no document/service
entity to derive `service` from), so they fall through to the unchanged
LLM path -- the user-visible outcome for these specific messages is
identical to before this fix. The original failing case (`ανοιχτά`-framed)
still hasn't recurred with a clearer pattern.

## ~~4. `service` field has no validation guardrail~~ -- fixed, see `fix-003`

Was the most consistently reproducible issue across every batch (4 distinct
invented values: English translation, type-name echo, English noun,
transliteration). Now requires `service` to actually appear in the message,
same guardrail `entities` already had. See `fix-003-service-field-guardrail.md`
for the fix and before/after evidence.

## ~~5. `schedule` action is never actually produced -- misclassified as `cancel`~~ -- fixed for fast-path-eligible messages, see `fix-016`

Was "action vocabulary gaps": `ACTIONS` was missing `cancel`/`schedule`, both
real messages fell back to the safe `unknown`. `fix-011` added both. Testing
afterward found this wasn't a clean win -- "Χρειάζομαι να κλείσω ραντεβού για
την Δευτέρα." (book an appointment) got classified `action: "cancel"`, not
`schedule`. `schedule` has never actually been produced in testing.

This is a regression in one specific way: this message used to safely fall
back to `unknown` (leading to the generic, safe template); now it confidently
tells the user to CANCEL when they were trying to BOOK.

**Status:** open, not yet fixed. `ACTIONS` is passed to the LLM as a bare
word list, same shape `INTENTS` used to be before `fix-002` added
`INTENT_DEFINITIONS` -- which fixed several real misclassifications by
teaching the general rule rather than leaving categories to be inferred from
the word alone. Same fix likely needed here: a one-line definition
distinguishing "wants to remove an existing booking" (`cancel`) from "wants
to create a new booking" (`schedule`). Not attempted yet -- see `fix-011` for
full detail.

**Fixed (`fix-016`, 2026-08-06), for messages that reach the fast path.**
`intent_rules.py`'s `schedule`/`cancel` indicators share zero vocabulary
(no reliance on the word "ραντεβού" alone, which both messages contain).
Confirmed on the *exact* message from this item's original bug report --
"Χρειάζομαι να κλείσω ραντεβού για την Δευτέρα." now resolves
`action="schedule"` correctly, via the fast path, reproduced identically
across three separate full-batch runs. The underlying gap this item
describes (`ACTIONS` still a bare word list, no `ACTION_DEFINITIONS`) is
**not fixed** -- it's now just unreachable for messages confident enough
to skip the LLM. A schedule/cancel message that doesn't clear the fast
path's confidence gate (e.g. no derivable `service` entity) would still
hit this exact bug on the unchanged LLM path. Fixing `ACTIONS` itself
remains a smaller, separate, still-worthwhile follow-up.

**Strongest evidence yet (`fix-016` patch notes, 2026-08-06):** matched
the archived pre-fast-path eval baseline against all three post-fast-path
runs by exact question text -- the baseline itself still produced
`action="cancel"` on this exact message (the bug, still live, right up
until this fix), while all three new runs agree on `action="schedule"`. A
real same-input regression test, not just a forward-looking gold-set case.

## 6. Compound/multi-clause messages blend two sub-requests inconsistently

"Θέλω να κάνω αίτηση για άδεια γάμου και να μάθω πόσο κοστίζει." (apply for a
marriage license AND find out the cost) and a similar gas-connection message both
resolved with `action` reflecting the first clause and `answer_type` reflecting
the second clause -- a consistent pattern, but the single flat record represents
neither sub-request cleanly.

**Status:** known limitation from the original design discussion (no clause
splitting, by choice, to keep the pipeline simple). Not necessarily something to
"fix" -- flagged here so it stays visible while we decide if/when it matters
enough to revisit.

New variant seen: "Ο δρόμος έχει λακκούβες εδώ και μήνες, πότε θα επισκευαστεί;"
(potholes for months, when will it be fixed) -- arguably both a complaint
(longstanding problem) and a question (asking when it'll be fixed). This time,
instead of blending fields like the earlier examples, it fully collapsed to
`intent: "question"` and dropped the complaint signal entirely. Same root cause
(no clause splitting), different symptom (full flip instead of partial blend).

**Not fixed by `fix-016`** -- `intent_rules.py` does no clause-splitting
(that's this file's separate, still-deferred backlog item). One incidental
observation from testing it, not a fix: the marriage-license-and-cost
compound case now commits via the fast path (`service` populated from a
real entity, `answer_type="cost"` genuinely traced to the "πόσο κοστίζει"
half) instead of the LLM path's `clarification_needed` -- arguably a
better fallback for that one case, but the root blending problem this item
tracks is untouched.

## ~~7. "θέλω να" phrasing can override real complaint content~~ -- structurally fixed for fast-path-eligible messages, see `fix-016`

"Θέλω να υποβάλω παράπονο για τον θόρυβο στη γειτονιά." (I want to file a
complaint about noise in the neighborhood) resolved to `intent: "request_service"`,
not `"complaint"` -- even though the content is literally someone filing a
complaint. The `request_service` definition's phrasing signal ("θέλω να..." =
statement of desire) won out over the fact that "παράπονο" (complaint) is right
there in the sentence.

This is a genuine tension in the definitions from `fix-002`, not clearly a bug:
"I want to file a complaint" really is a statement of desire for the
municipality to process something (the complaint), so `request_service` isn't
unreasonable either. Also relevant: the entity extractor caught `"παράπονο"` as
a `service` entity, which is arguably wrong in either reading -- filing a
complaint isn't a municipal service being requested, it's the action itself.

**Status:** one instance, and genuinely ambiguous rather than a clear miss. Worth
watching for more "I want to complain/report X" phrasings before deciding whether
`complaint`'s definition needs to explicitly claim this pattern.

**Fixed (`fix-016`, 2026-08-06), for messages that reach the fast path.**
`intent_rules.py`'s `request_service` indicators deliberately contain no
bare "θέλω"/"θέλω να" anywhere (every phrase names a concrete verb) --
unlike v1's own rule engine, which does list bare "θέλω" and would have
reintroduced exactly this ambiguity if ported directly. This message now
resolves `intent="complaint"` correctly via the fast path, reproduced
identically across three full-batch runs. Structural, not tuned: nothing in
"Θέλω να υποβάλω παράπονο..." matches any `request_service` phrase at
all, so there's no tension to resolve by threshold. As with #5, this
doesn't touch the LLM path's own `INTENT_DEFINITIONS` tension -- a
complaint phrased this way that doesn't reach the fast path (e.g. no
clear complaint keyword) could still hit the original ambiguity there.

**Strongest evidence yet (`fix-016` patch notes, 2026-08-06):** matched
against the archived pre-fast-path baseline by exact question text -- the
baseline itself still produced `intent="request_service"`, `service=None`
on this exact message, while all three new runs agree on
`intent="complaint"`, `service='παράπονο'`. Same real same-input
regression-test evidence as #5 above.

## 8. Entity span sometimes truncated to a generic sub-phrase

"Θέλω να κάνω αίτηση για άδεια λειτουργίας καταστήματος." (apply for a business
*operating license*) extracted the entity as `"άδεια λειτουργίας"` (operating
license), dropping `καταστήματος` (of the store) -- the general part of the
phrase without the qualifier that makes it a specific, real service name.

**Status:** recurrence confirmed, no longer just one instance. The
2026-08-06 34-case eval batch (`pipeline/logs/eval_summary_2026-08-06.md`,
reproduced identically in both the pre- and post-`fix-014` runs) found
several more, on both `service` and full entity spans: "μεταφορά" alone for
a recycling-bin relocation question (dropping "κάδου ανακύκλωσης"),
"διεύθυνσης" alone for an address-change declaration (dropping "αλλαγή
κατοικίας"), "στήριξης" alone for an unemployment-support question
(dropping "πρόγραμμα...ανέργους"), and one case (moving a garbage bin) where
`service` didn't resolve at all rather than truncating. This interacts
directly with the gazetteer's word-overlap gates (`fix-013`/`fix-014`): a
truncated single-word `service` can structurally never clear the 2-word
requirement regardless of whether the real, un-truncated service would have
matched fine -- so this entity-extraction gap is now also a *cause* of
`kb_match` false negatives downstream, not just an entity-quality issue on
its own. Worth prioritizing if the clause-splitter (top of `backlog.md`)
isn't picked up first, since it's now the best-evidenced open entity/service
extraction gap.

**Also now a fast-path coverage cost (`fix-016`, 2026-08-06).**
`intent_rules.py`'s `_derive_service` reads straight from the same
entities this item is about -- a truncated span (e.g. "ανακύκλωσης"
instead of "κάδου ανακύκλωσης", seen in `fix-016`'s eval batch) is what
the fast path ends up trying to look up, same as the LLM path already
does. Not a new failure mode, just a second consumer now depending on the
same, still-open entity-quality gap.

## ~~9. `kb_match` produces confidently wrong-purpose matches, not just for complaints~~ -- largely fixed, see `fix-013`

`fix-009` found this for complaints specifically (2 of 3 real matches were
topically adjacent but functionally wrong -- billing dispute matched to "pay
your bill", broken bin matched to "relocate your bin") and special-cased
complaints to never use `kb_match`. Testing `question`/`request_service`
intents afterward found the same failure, arguably worse: "excavation permit"
matched to "civil marriage license for foreigners" (0.317), "passport
issuance cost" matched to "municipal tax clearance issuance" (0.319) -- 0 of
2 matches were right, and the excavation/marriage-license pair shares nothing
but the generic word "άδεια" (permit/license).

Checked whether a stricter score threshold would fix it (see
`tried-and-failed.md`) -- it doesn't. Every match seen in testing, sorted by
score, has bad matches *between* the two good ones (0.317 bad, 0.319 bad,
0.324 bad, 0.373 **good**, 0.420 bad, 0.774 **good**) -- no cutoff keeps both
good matches while dropping every bad one.

**Status:** partially fixed by `fix-010`. Both of the confirmed
`question`/`request_service` bad matches (excavation permit, passport) turned
out to be caused by shared generic administrative words ("άδεια", "έκδοση")
and are now fixed by stripping those from matching. But that's not the whole
problem -- the 2 complaint-side bad matches (water bill, recycling bin) are a
different failure mode entirely (real content-word overlap with a
topically-right-but-purpose-wrong title, not a generic-word coincidence), and
stripping generic terms doesn't touch that. Those 2 are currently masked only
because `fix-009` routes all complaints away from `kb_match` regardless --
the underlying gazetteer behavior for that failure mode is unfixed, just
unreachable for complaints specifically.

**Update (`fix-011` testing):** confirmed this reaches `request_service` too,
via a new example -- "Θέλω να ακυρώσω το ραντεβού μου" / "κλείσω ραντεβού"
both matched "Απομάκρυνση ογκωδών αντικειμένων με ραντεβού" (bulky-item
removal by appointment) purely because `service` resolved to the bare word
"ραντεβού" with no indication what the appointment was for. Not the same
mechanism as the water-bill/bin case (no shared generic word here --
"ραντεβού" is a real content word, just uninformative alone), but the same
underlying risk: nothing currently protects `question`/`request_service` from
a wrong-purpose match the way `fix-009` protects complaints.

Also positive evidence, though: re-tested the exact water-bill/bin pattern
directly on `question` and `request_service` phrasings of the SAME
underlying situations (e.g. "how much to move the recycling bin", phrased
as both a question and a request) and both matched correctly (0.548) --
so the gazetteer isn't broken generally, it correctly matches when the
message's real purpose actually aligns with the KB title's purpose. The
risk is specifically messages where `service` is too vague/generic to
signal purpose (like a bare "ραντεβού"), not `question`/`request_service`
messages broadly.

**Update (`ipiresies.pdf` cross-check, 2026-08-05):** more real examples of
the `fix-010`-unfixed failure mode (real content-word overlap with a
topically-adjacent-but-wrong title), found by running confirmed
not-implemented service names directly through `find_kb_match` (see
`backlog.md`'s "Confirmed not-yet-implemented services" entry for the full
cross-check). Two clean examples: `μεταφορά_οστών` (transfer of remains)
matched "Μετακίνηση...κάδων" (moving garbage bins) via the shared word
"μεταφορά"; `επέκταση_δικτύου_ύδρευσης` (water network expansion) matched
"Βλάβες...δημοτικού φωτισμού" (lighting network faults) via the shared word
"δικτύου". 13 more matches of similar quality found in the same pass. This
is the largest batch of confirmed instances of this specific failure mode
yet -- worth prioritizing over the vague-query (`ραντεβού`) variant above if
either gets picked up next, since it's now the better-evidenced pattern.

**Resolved (`fix-013`, 2026-08-06):** `best_match` (the function `find_kb_match`
actually calls, and the one that had no protection at all until now) now
requires 2+ shared content-word stems between query and title, closing the
exact gap this whole item tracked -- `find_service_entity` had this
protection since `fix-004`, `best_match` never did. Fixed 14 of the 15
concrete bad matches found across `fix-009`/`fix-011`/`fix-012` testing,
confirmed both by direct calls and end-to-end through the real pipeline with
LLM-resolved `service` strings (zero bad matches across a 6-message batch).
One residual case remains and is expected to stay unresolved by word-overlap
alone: `τέλη καθαριότητας κοιμητηρίων` (cemetery cleaning fees) still matches
a general lighting-and-cleaning fee title on 2 genuine shared content words
(τέλη, καθαριότητας) -- a real topic-overlap, different-scope case, not a
coincidental collision. See `fix-013` for full evidence and reasoning on why
this one case is being left as a documented limitation rather than chased
further right now.

**Follow-up (`fix-014`, 2026-08-06):** `fix-013`'s flat "require 2 shared
words" turned out to have its own false-negative cost, found while
investigating what first looked like a bad match on "χορήγηση άδειας
γάμου" (that specific case turned out to be a genuinely ambiguous query,
not a bug -- see `fix-014`'s writeup for the correction). The real bug:
7 of 164 KB titles (e.g. "Κατασχέσεις", "Βεβαίωση Υψομέτρου") only have 1
real content word left after generic-term stripping, so a flat "2" was
mathematically impossible to satisfy for them -- confirmed unmatchable
even when queried with their own exact title text. Fixed by scaling the
requirement to `min(2, title's own content-word count)` -- titles with 2+
real words keep the full fix-013 protection; titles with only 1 no longer
need a word they can never provide.

- `complaint` classification has now generalized correctly across 4 phrasings
  sharing almost no vocabulary: "no response in two weeks", "wrong water bill",
  "broken street lighting", and "there's a water leak on X street" (this last one
  is a neutral factual report, no dissatisfaction language at all -- still
  correctly read as "reporting a problem" per the definition).
- The `question` vs `request_service` boundary is holding up on tricky phrasing,
  not just easy cases -- "θέλω να μάθω..." (I want to *know*...) is correctly
  read as information-seeking (`question`), not action-seeking
  (`request_service`), despite starting with the same "θέλω να" pattern our
  request_service examples use.
- `fix-003`'s `service` guardrail held up clean on an entirely fresh batch: zero
  invented values across 6 messages (versus 4 distinct bad values seen before the
  fix), and one genuine real value ("βεβαίωση μόνιμης κατοικίας") correctly
  passed through rather than being over-blocked.
