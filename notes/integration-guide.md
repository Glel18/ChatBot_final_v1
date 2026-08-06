# Integration guide (for whoever builds step 6, the GUI)

The pipeline is deliberately framework-agnostic -- nothing in `pipeline/`
knows or cares what's calling it. This is the whole interface:

```python
from structured_intent import resolve_structured_intent
from answer_composition import compose_answer

result = resolve_structured_intent(user_message)   # dict: intent, service,
                                                     # action, entities,
                                                     # kb_match, etc.
answer = compose_answer(result)                     # {"text": ..., "source": ...}
display(answer["text"])                             # what goes on screen
```

That's it for the happy path. Everything below is what isn't obvious from
just reading those two function signatures.

## Setup

- `pip install -r pipeline/requirements.txt` (`requests`, `scikit-learn`).
- Ollama running locally (`ollama serve`), with `qwen2.5:7b` pulled
  (`ollama pull qwen2.5:7b` -- see `ollama_client.py`'s `MODEL` constant if
  that ever changes).
- No other setup. `gazetteer.py` reads `data/heraklion_eservices.json` at
  import time; nothing needs to be built or downloaded beyond the above.

## Latency -- do not call this synchronously on a UI thread

Each message costs 1-2 LLM calls: `entity_extraction`'s LLM fallback
always runs, `structured_intent_llm` runs only if the rule-based fast path
(`intent_rules.py`, `fix-016`) didn't already resolve the message with no
model call at all -- check `record["intent_source"]`
(`"rule_fast_path"`/`"llm"`) and `metrics.llm_calls` on any logged record
for exactly what ran for that message.

Before the fast path existed (`pipeline/logs/eval_summary_2026-08-06.md`,
34-case batch): 10.1-30.2 seconds end to end, ~19.7s mean, every message.

After the fast path, run three times for reproducibility (`pipeline/logs/
eval_log_run1/2/3_2026-08-06_fast-path.jsonl`): **23/40 messages (58%),
identical across all three runs, hit the fast path** with no LLM call for
`structured_intent_llm` at all. Chart:
[Fast-path eval comparison](https://claude.ai/code/artifact/8f670ed3-e7b8-43cc-81e8-17bf35ba1cc1).
Matching the pre-fast-path baseline against all three runs by exact
question text (not position) gives a real same-question comparison, not
just a different batch:

| | Baseline | Run 1 | Run 2 | Run 3 |
|---|---|---|---|---|
| Mean, same 34 questions | 23.2s | 16.9s | 10.9s | 15.8s |
| Fast-path subset mean | -- | 9.3s | 6.8s | 8.5s |
| LLM-path subset mean | -- | 24.5s | 15.0s | 23.2s |

27-53% overall reduction depending on the run (absolute times move with
system/Ollama load, same as every latency number in this project -- the
fast-path-vs-LLM-path *ratio* is the stable part: consistently ~2.5-3x
faster). Still not milliseconds either way -- a naive synchronous call
will still freeze the window for the LLM-path messages. `gui.py` (the old
BERT-based pipeline's GUI, still in the repo root) already has a pattern
for this -- a `STATE` dict with ready/loading flags, worth adapting rather
than reinventing.

If this needs to get faster later, `metrics.llm_calls` on every logged
record already shows which LLM call costs more per message
(`structured_intent_llm` ran ~11.5s mean vs. `entity_extraction_llm`'s
~8.1s mean in the pre-fast-path batch) -- that's where to look first, not
a guess. `entity_extraction_llm` is NOT addressed by `fix-016` and still
runs unconditionally, every message, regardless of `intent_source`.

## Error handling -- `OllamaUnavailableError`

`ollama_client.call_ollama` raises `OllamaUnavailableError` (not a raw
`requests` exception) if Ollama can't be reached, times out, or errors out.
This is deliberately NOT caught anywhere inside `pipeline/` -- it propagates
up through both `resolve_structured_intent` and `compose_answer`'s caller.
Catch it wherever the GUI calls the pipeline and show something like "service
unavailable, try again" -- see `run.py`'s `__main__` block for a minimal
reference (catches it per-message, keeps the session alive rather than
crashing).

This is a genuinely different situation from the pipeline "running fine but
not finding anything" (empty entities, `kb_match: None`, etc.) -- those are
handled gracefully already and don't raise. `OllamaUnavailableError` means
nothing ran at all.

## Known limitations -- read before shipping

`open-weakpoints.md` in this same folder is the live list of known,
unresolved issues -- e.g. compound/ambiguous message patterns don't
resolve cleanly (#6). Two items that used to be here -- `schedule` actions
misclassifying as `cancel` (#5), and complaints phrased as "θέλω να..."
drifting toward `request_service` (#7) -- are now fixed **for messages
that reach the rule-based fast path** (`fix-016`), but the underlying gaps
on the LLM path itself (a bare `ACTIONS` word list, the `INTENT_DEFINITIONS`
tension) are still there for messages that don't hit the fast path. Check
`intent_source` on the record if either of these ever resurfaces --
`"llm"` means the old, still-open gap; `"rule_fast_path"` would be a new
regression worth its own investigation. None of these crash anything, but
a UI built on top should know they exist rather than be surprised by them
later. `fix-NNN-*.md` files have the full history and evidence behind
every design decision, if something behaves unexpectedly and it's worth
knowing why before "fixing" it again.

`kb_match` pointing to a real but wrong-purpose service (open-weakpoints #9)
was the main reliability risk going into this handoff -- `fix-013` closed
most of it: `best_match` now requires 2+ shared content words before
returning a match, fixed 14 of 15 known bad cases, confirmed end-to-end with
real LLM-resolved queries. One residual case remains and is expected to
recur in similar shape: two genuinely shared content words can still point
to a same-topic-but-wrong-scope service (e.g. a specific fee matching a
different, more general fee). This isn't a crash or an empty result -- it's
a wrong answer presented confidently, which is the one failure mode most
worth a human spot-checking for if `kb_match` results ever look off. See
`fix-013` for the full mechanism and why it's not chased further right now.

`fix-013`'s 2-word requirement had its own side effect, caught and fixed
the same day: 7 of 164 KB titles only have 1 real content word after
generic-term stripping, which made them permanently unmatchable (any query,
including the exact title text itself, came back `None`). `fix-014` scaled
the requirement to what each title can actually offer, restoring those 7
without reopening the false-positive problem `fix-013` fixed. No other
titles were affected -- if a real service seems unreachable through
`kb_match` after this, it's worth checking fresh rather than assuming it's
this same class of bug again.

## Logging (optional, but recommended)

`run.py`'s `run_and_log` shows the pattern used throughout testing: append
one JSON object per message to `pipeline/logs/eval_log.jsonl`, including the
composed answer and which template branch produced it (`answer_source`).
Reusing this (or something like it) from the GUI would mean real usage keeps
building the same evaluation dataset that's been used to find and fix
everything documented in this folder so far -- valuable to keep, not
required to.

Each logged record also carries a `metrics` block (added 2026-08-06):
`total_pipeline_ms`, the `resolve_structured_intent_ms`/`compose_answer_ms`
split, and a `llm_calls` list (one entry per actual LLM call made for that
message, each tagged with a `label` -- e.g. `entity_extraction_llm`,
`structured_intent_llm` -- and its own `duration_ms`). This is where the
end-to-end timing estimate in the Latency section above actually comes
from; if real usage after handoff shows notably different numbers, this is
the field to check first. `run_and_log(text, **extra_fields)` also
accepts arbitrary extra keyword args merged into the logged record before
it's written -- `run_full_eval.py` uses this for `test_category`/`expected`
labels, and a GUI could do the same for e.g. a session or user ID, without
needing to change `run_and_log` itself.

Two more fields added with the fast path (`fix-016`)/validator (`fix-015`):
`intent_source` (`"rule_fast_path"` or `"llm"` -- which path actually
produced this record) and `validation_errors` (only present on
`"llm"`-sourced records -- a list of invariant violations `validator.py`
found, empty on every clean record; see `fix-015` for what it checks).
Both are useful for exactly the kind of thing this Logging section is
about: if real usage after handoff shows a class of wrong answers, check
`intent_source` first to know which code path to actually look at.
