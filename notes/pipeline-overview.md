# Pipeline overview -- start here

A walkthrough of what's in `pipeline/` and how a message
flows through it, for anyone new to this codebase. Each file below does
exactly one job; nothing is generic or reused across concerns beyond what's
noted. For the *history* of why each piece looks the way it does (bugs
found, fixes tried, evidence), see the `fix-NNN-*.md` files and
`open-weakpoints.md` -- this doc is the map, those are the logbook.

## How this pipeline came together

Not built top-to-bottom in one pass -- each step was built, tested against
real Greek messages, and fixed based on what that testing actually showed,
in roughly this order. Skimming this before the file-by-file section below
gives the *why* behind decisions that would otherwise look arbitrary reading
the code cold.

**1. Entity extraction came first, and started weaker than expected.**
The first version leaned entirely on the LLM to spot dates/documents/
services, and testing found it recalling zero entities on obvious cases
(`fix-001`) -- fixed with few-shot examples and accent-insensitive matching,
but that also surfaced a deeper pattern: the model was *inconsistent* in a
way that had nothing to do with sentence difficulty (catching "Δευτέρα" but
missing "Σάββατο" in equivalent sentences). That inconsistency is what
motivated pulling dates out into pure rules (`date_rules.py`) and services
out into a KB-matching gazetteer (`gazetteer.py`) instead of trying to
prompt-engineer the LLM into being more reliable at something rule-based
matching could just solve outright (`fix-004`). The LLM was demoted to a
fallback for whatever those two couldn't handle, not removed.

**2. Intent resolution needed definitions, not just category names.** Early
testing of `structured_intent.py` found real messages misclassified when
the prompt just listed `request_service`/`question`/`complaint`/`other` as
bare words -- a complaint read as a question, a cost question read as
"other" (`fix-002`). Writing one-line definitions per category (what
distinguishes a request from a question, specifically) fixed multiple
misclassifications at once, without adding a single example -- the
general takeaway that shaped every vocabulary added afterward (`ACTIONS`
in `fix-011` used the same pattern). Separately, the `service` field
turned out to have zero validation and was returning fully invented values
(English translations, transliterations) -- fixed with the same
substring-of-the-message guardrail entities already had (`fix-003`).

**3. Wiring entities and intent together, without letting them
contradict each other.** Once both steps existed, the obvious next
question was what happens when they disagree -- e.g. entity extraction
finds a document but `service` comes back null. Rather than adding a
second LLM call to "reconcile" them (which just reintroduces two
independently-guessing signals that can disagree, the exact failure mode
being designed around), `fix-005` added a cheap code-only consistency
flag for human review instead. This "compose, don't duplicate" principle
-- entities computed once, passed into intent resolution as trusted given
facts, never re-derived -- became the standing rule for the rest of the
build.

**4. The KB lookup, and then a long fight against wrong-purpose
matches.** `fix-006` wired up real KB titles/URLs so answers could point
somewhere real instead of a generic response. This is where most of the
later debugging effort went: `fix-009` found complaints getting
confidently pointed to a topically-adjacent but functionally wrong page
(a billing dispute matched to "pay your bill") and special-cased
complaints to never trust `kb_match`; `fix-010` found the same problem
on `question`/`request_service` messages, traced it to shared generic
bureaucratic words ("άδεια", "αίτηση") skewing the match, and fixed that
specific cause by stripping those words before scoring. `fix-012` was a
detour that turned out to matter a lot: cross-referencing a human-audited
PDF of the real service catalog against the KB found 15 more concrete
wrong-purpose matches in one pass, which became the evidence base for
`fix-013` -- closing the actual structural gap (`best_match` never had
the same "2+ shared real words required" protection `find_service_entity`
had since `fix-004`) and fixing 14 of those 15. One residual case is
documented, not hidden -- see `fix-013` and `open-weakpoints.md` #9.
`fix-013`'s own fix had a side effect, caught the same day via a
comprehensive eval batch (`pipeline/logs/eval_summary_2026-08-06.md`): a
flat "2 shared words" made 7 of 164 KB titles -- ones with only 1 real
content word to begin with -- permanently unmatchable, confirmed by
querying them with their own exact title text and still getting nothing.
`fix-014` scaled the requirement to what each title can actually offer,
restoring all 7 without reopening the false-positive problem `fix-013`
fixed.

**5. Answer composition came last, deliberately template-only.** Once
`kb_match` existed, `fix-007` built the straightforward case (template
answer grounded in the real title/URL), and `fix-008` filled in every
case where no match exists at all (complaint, small talk, unresolved
service, genuine KB gap) so the pipeline always returns *something*
instead of `None`. No LLM call anywhere in this file, on purpose -- the
same hallucination risk `fix-003`'s guardrail was built to prevent in the
`service` field would just reappear in the final answer text otherwise.

**6. Handoff prep, once the core loop was solid.** `requirements.txt`,
`OllamaUnavailableError` (a distinct, catchable failure for "Ollama isn't
running" vs. "the model gave a bad answer"), and
`notes/integration-guide.md` were added once the pipeline itself was
considered functionally stable, specifically so a separate team building
the GUI (step 6) wouldn't need to reverse-engineer any of the above from
the code alone.

**7. Latency, after handoff prep, once there was a v1-vs-v2 comparison to
learn from.** A side-by-side look at v1's `structured_intent/` pipeline
found it winning on latency for a concrete, portable reason: a rule-based
first pass (`rule_engine.py`) that resolves confident, unambiguous
messages without an LLM call at all, plus a single centralized validator
(`validator.py`) every layer's output passes through. Neither was a
copy-paste job -- v1's taxonomy doesn't map onto v2's (v1 has no
`complaint` intent, folding fault reports into `request_service` instead,
so its own indicator phrases would have reintroduced v2-specific
ambiguities like `fix-002`'s `complaint`-vs-`request_service` tension).
`fix-015` built the validator first (`validator.py`), since the fast path
needed something to validate its own output against before either
existed; `fix-016` built the fast path second (`intent_rules.py`, plus a
new leaf module `taxonomy.py` to avoid a circular import between the two).
Result, measured twice for reproducibility: roughly 55-65% of a
message's latency saved on the ~58% of real messages confident enough to
skip the LLM call entirely.

The file-by-file section below is the resulting *current state* of all of
that -- what each file does today, not the order it was built in.

## The shape of the pipeline

One user message goes through five steps, each handled by its own file --
files used at each stage are noted on the right:

```
user message (raw Greek text)
    |
    v
1. entity_extraction.py ---------------- entity_extraction.py
    |  "what facts are in this          date_rules.py    (dates)
    |   message?"                       gazetteer.py     (KB-matched service)
    |  (dates, documents, services,     ollama_client.py (LLM fallback for
    |   locations...)                                     location/other)
    v
2. structured_intent.py ---------------- structured_intent.py
    |  "what does the user want         taxonomy.py      (shared vocab)
    |   done with them?"
    |
    +--> intent_rules.py (fast path) --- intent_rules.py  (no LLM call --
    |      confident? commit.                              rule scoring)
    |
    +--> structured_intent_llm --------- ollama_client.py (LLM call, only
           not confident? ask the LLM.                     if fast path
                                                             abstained)
    |
    |  both paths converge here:
    |  validate + KB lookup ------------ validator.py     (record checks)
    |                                    gazetteer.py     (KB lookup)
    v
3. answer_composition.py --------------- answer_composition.py
    |  "what do we actually say         (template only, no LLM)
    |   back?"
    v
answer text + a URL, or an honest "I don't know, call this number"
       + intent_source/answer_source labels recording which path ran
```

`run.py` is the terminal harness that drives this end to end and logs every
result (`run_full_eval.py` drives the same thing in labeled batches). Every
file named above the arrows is shared machinery the two main steps call
into -- none of it is a separate pipeline "step" of its own.

## Design principles that explain most of the code

A few decisions repeat across every file, so it's worth naming them once
instead of re-explaining per file:

- **Rules and lookups first, LLM only for the genuine residue.** Dates are
  a fixed list + regex (`date_rules.py`). Service names are matched against
  the real KB (`gazetteer.py`). Confident, unambiguous intent/action/
  answer_type resolutions go through weighted keyword scoring
  (`intent_rules.py`) before ever reaching a model call. The LLM
  (`ollama_client.py`, model `qwen2.5:7b` via Ollama) only fills in what's
  left after all of those -- mainly `location`/`other` entities and the
  genuinely ambiguous judgment calls no rule list resolves confidently.
- **Compose, don't duplicate.** Entities are extracted once in step 1 and
  passed into step 2's prompt as *given facts*, never re-derived. Two
  independently-produced signals that can silently disagree was a real bug
  class early on -- this structure makes it impossible by construction.
- **Every LLM-sourced value is validated in code, not trusted from the
  prompt.** An entity or a `service` string is only kept if it's an actual
  substring of the original message (accent/case-insensitive). This is what
  stops the model from inventing values that don't exist in the input.
- **Small, closed vocabularies, grown only when real messages need it.**
  `ENTITY_TYPES`, `INTENTS`, `ACTIONS`, `ANSWER_TYPES` all started minimal
  and only gained entries once testing showed a real message with nowhere
  good to go.
- **No LLM in the final answer.** `answer_composition.py` is templates
  only, grounded in a real KB title + URL or an honest "I don't know."
  Never generates freeform text that could hallucinate.

## File by file

### `entity_extraction.py` -- step 1: what facts are in this message?

Pulls out concrete mentions: which document, date, service, location. Tries
three sources in order, cheapest and most certain first:
1. `date_rules.find_dates` -- weekday names, relative phrases, absolute
   date regex. No model call, so it's deterministic.
2. `gazetteer.find_service_entity` -- matches the message against real KB
   service titles. Also no model call; only fires when confident.
3. LLM fallback, for whatever's left (mainly `location`/`other`, and
   `document`/`service` if the gazetteer found nothing).

Only the LLM's output passes through a validity check
(`_is_valid_entity`) -- the rule/gazetteer sources can't hallucinate by
construction, since they only ever return real substrings of the message.

### `date_rules.py` -- deterministic date matching

Pure regex + two fixed lists (7 weekday names, a handful of relative-date
phrases like "αύριο"/tomorrow). No LLM. Exists because testing showed the
model being *inconsistent* on this specific entity type for no good
reason (catching "Δευτέρα" but missing "Σάββατο" in equivalent sentences)
-- Greek has a small, genuinely closed vocabulary here, so a fixed list is
strictly better than asking a model to guess every time.

### `gazetteer.py` -- matches messages against the real service catalog

Loads the 167 real municipal service titles from
`data/heraklion_eservices.json` once at import time, and builds a fuzzy
text-matching index over them (TF-IDF: character n-grams blended with
word-level overlap, so it tolerates Greek's grammatical inflection). Two
public entry points:
- `find_service_entity(text)` -- used by step 1, returns a validated
  *span* of the original message for the entities list.
- `find_kb_match(query)` -- used by step 2, returns the actual KB record
  (title + URL) for a resolved `service` string, which is what
  `answer_composition.py` links to.

Also does two rounds of noise-filtering before scoring a match: strips
generic bureaucratic words ("άδεια"/permit, "αίτηση"/application, etc. --
these appear in dozens of unrelated titles and cause false positives on
their own), and requires at least 2 real shared content words between the
query and the winning title before accepting it (a single shared word,
often a coincidental proper noun, isn't enough evidence). Both of these
were added after real wrong-purpose matches were found in testing -- see
`fix-010` and `fix-013`.

### `ollama_client.py` -- shared LLM call wrapper

One function, `call_ollama(prompt)`, used by both step 1 and step 2 so the
HTTP-call logic (endpoint, model name, JSON-constrained output,
`temperature=0` for repeatable results) lives in exactly one place. Also
defines `OllamaUnavailableError` -- raised when Ollama itself can't be
reached (not running, model not pulled), which is a genuinely different
situation from "the model ran and gave a low-quality answer." This is
deliberately left uncaught inside the pipeline so a caller (like a future
GUI) can show "service unavailable, try again" instead of the pipeline
silently pretending nothing matched.

### `structured_intent.py` -- step 2: what does the user want done?

Takes the raw message *and* the entities from step 1, and resolves:
- `intent` -- request_service / question / complaint / other
- `action` -- apply / renew / pay / cancel / schedule / check_status / unknown
- `answer_type` -- cost / deadline / requirements / procedure / contact / other
- `service` -- the specific service name, validated the same way entities
  are (must be a real substring of the message)

Needs the raw sentence again (not just the entity list) because intent
lives in sentence structure -- "when does my ID expire" and "I want to
renew my ID" can mention the exact same document but need opposite
answers.

Tries `intent_rules.resolve_intent_fast` (below) first -- no LLM call. On
a confident commit, the candidate goes through `validator.validate_or_raise`
as a hard gate (a failure here is treated exactly like an abstain) before
being returned. Falls through to the unchanged LLM call otherwise. Either
way, the record is assembled by a shared `_finalize` helper: once
`service` is resolved (whichever path produced it), it calls
`gazetteer.find_kb_match(service)` to attach a real KB title/URL
(`kb_match`), and computes `entity_service_consistent` -- a cheap
code-only check (not a second LLM call) that flags when `service` and the
entities from step 1 disagree, for human review during evaluation rather
than automatic correction. Every record also carries `intent_source`
(`"rule_fast_path"` or `"llm"`), so which path produced it is visible in
the log, not just claimed.

### `taxonomy.py` -- the three shared vocabularies

`INTENTS`/`ACTIONS`/`ANSWER_TYPES` -- pulled out of `structured_intent.py`
into their own tiny leaf module once a second and third consumer showed up
at once (`validator.py` needs to check records against them,
`intent_rules.py` needs them as its indicator-dict keys), and both of
those are imported BY `structured_intent.py` -- so `structured_intent.py`
owning the vocab itself would make either import a cycle. Nothing imports
back from this module; same principle `date_rules.py` already models for
pulling a sub-concern out of a module that would otherwise need to import
its own dependent. `INTENT_DEFINITIONS` (the LLM prompt text) stays in
`structured_intent.py` -- that's prompt engineering, not a vocabulary
other modules need.

### `intent_rules.py` -- the rule-based fast path

A deterministic alternative to `structured_intent.py`'s LLM call: scores
`intent`/`action`/`answer_type` by counting weighted keyword-indicator
phrase hits (longer, more specific phrases outweigh short generic ones),
and only commits when the top score clears a minimum *and* beats the
runner-up by a margin -- otherwise it abstains and the caller falls
through to the LLM, exactly as if this module didn't exist. No model
call, no I/O -- same "pure rules, no lookups" shape `date_rules.py`
already establishes, for the same reason: a real fraction of messages
have unambiguous enough signal to resolve deterministically.

Also derives `service` directly from the entities `entity_extraction.py`
already found (the longest `document`/`service`-typed entity text) --
without this, skipping the LLM call wouldn't actually save the latency
this module exists for, since `service` would still need resolving
somehow. Abstains specifically when `request_service`/`question` has no
such entity to draw from, since those are the only two intents where
`service`/`kb_match` change the composed answer. `constraints` is always
empty on a fast-path commit -- an explicit, logged trade-off, not a
silent drop.

The indicator phrases were adapted from v1's `structured_intent/
rule_engine.py` (same scoring mechanism, proven: v1's own gold-set eval
scored 16/16), but built fresh, not ported -- v1 has no `complaint`
intent at all, so its actual phrase lists (which include bare "θέλω" as a
`request_service` indicator) were never tested against v2's specific
complaint-vs-request_service ambiguity. See `notes/fix-016` for the full
design reasoning and evidence, including which known weak points this
does and doesn't fix.

### `validator.py` -- centralized record guardrails

Checks a resolved record against the invariants it's supposed to satisfy
-- required fields, `intent`/`action`/`answer_type`/entity-type enum
membership, well-formed/deduplicated entities, and one cross-field rule
(`service` can't be null while a document/service entity is present).
Two calling conventions, used deliberately differently: `validate_structured_intent`
never raises (used as a soft, logged-for-review check on the LLM path --
`structured_intent.py`'s existing safe-default coercion already prevents
most of what this checks, so this is defense-in-depth, not a new gate on
anything reachable there); `validate_or_raise` does raise, used as a hard
gate on the fast path's candidate record specifically, since that's the
one place with no guardrail at all before this existed -- and the failure
is caught one frame up and treated like an abstain, so it never actually
reaches a user. See `notes/fix-015` for the full design reasoning
(including why the hard/soft split, not one global answer) and evidence.

### `answer_composition.py` -- step 5: what do we actually say?

Turns the structured record into a Greek answer string, using plain string
templates only -- no LLM call anywhere in this file. Branches in order:
1. `complaint` -- always the same acknowledgment + phone number, regardless
   of `kb_match`. Testing found `kb_match` pointing to a real but
   functionally-wrong page for complaints often enough that never trusting
   it here was safer than trying to filter the bad cases out.
2. `kb_match` present -- a template grounded in the real title/URL,
   worded differently depending on whether a specific `action` is known.
3. `other` (small talk) -- a fixed greeting-style reply.
4. `service` unknown -- asks the user to clarify, rather than guessing.
5. `service` known but no confident KB match -- an honest "couldn't find
   an exact match, here's the phone number" (this is the case for genuine
   KB gaps, like a service the municipality hasn't published online yet).

Every returned answer also carries a `source` label naming which of these
5 branches produced it, so the eval log shows at a glance how messages are
actually being handled.

### `run.py` -- the interactive test harness (and the shared run/log/print logic)

The whole pipeline's public interface is really just two functions:
`resolve_structured_intent` (steps 1+2) and `compose_answer` (step 5).
`run.py` is a small terminal loop around them: type a message, see the
full structured result plus the composed answer, repeat, `quit` to exit.

Two functions here do the real work, and both are also imported directly
by `run_full_eval.py` below rather than being reimplemented there:
- `run_and_log(text, **extra_fields)` -- runs one message through the
  pipeline, times it, appends the result to
  `pipeline/logs/eval_log.jsonl` (one JSON object per line), and returns
  the full record. Every record includes a `metrics` block: total time
  end to end, the resolve/compose split, and a `duration_ms` for every
  individual LLM call made (labeled by which step it was for, e.g.
  `entity_extraction_llm` vs `structured_intent_llm` -- entity extraction
  only calls the LLM as a fallback, so this can be 1 or 2 calls per
  message). `**extra_fields` lets a caller merge extra keys into the
  logged record without `run_and_log` needing to know what they mean --
  `run_full_eval.py` uses this for `test_category`/`expected` labels.
- `print_result(result)` -- the console output format (full JSON, then a
  one-line `>>> [source] (Nms) answer` summary), factored out so both
  harnesses below print identically instead of keeping two copies of the
  same formatting in sync by hand.

This eval log -- built one real message at a time through this file -- is
what most of the `fix-NNN` investigations were actually tested against.

### `run_full_eval.py` -- the batch regression suite

Not part of the pipeline itself, not imported by anything else -- a
standalone script for refreshing `eval_log.jsonl` with one big labeled
batch instead of typing messages into `run.py` one at a time. Defines
`CASES`: a fixed list of `(category, message, expected)` tuples covering
every category this project has needed while testing --
`simple`/baseline, `old-regression` (previously-broken cases that should
now be fixed), `unsure` (known ambiguous cases from `open-weakpoints.md`),
`not-implemented` (confirmed genuine KB gaps, should never match),
`implemented` (real KB titles, should match), and a few `new` messages
never run before. `expected` is a short human note on what a correct
result looks like -- checked by eye against the real output afterward,
not asserted automatically, since "correct" for a `kb_match` often means
"right title AND right purpose," which isn't a cheap thing to assert in
code.

Loops over `CASES` calling `run.run_and_log`/`run.print_result` directly
-- no separate pipeline-calling logic of its own, so a batch case and an
interactively-typed message are logged and printed in exactly the same
shape.

## What's NOT in this pipeline (by choice, not oversight)

- No conversation memory -- every message is resolved completely
  independently. A follow-up like "yes, that one" has no way to reference
  what came before.
- No clause-splitting -- a message with two requests in it ("I want to
  apply for X and also know the cost") gets one flat record, not two.
- No semantic/embedding-based matching -- `gazetteer.py` is lexical
  (TF-IDF) only, so it can find "same topic" but can occasionally get
  fooled by "same topic, different purpose."

(A rule-based fast path and a centralized schema validator used to be
listed here too -- both shipped, see `intent_rules.py`/`validator.py`
above and `notes/fix-015`/`fix-016`.)

All three are real, tracked ideas -- see `backlog.md` for the reasoning
behind deferring each, and `open-weakpoints.md` for the concrete cases that
motivated them.
