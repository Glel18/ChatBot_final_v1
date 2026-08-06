"""
ollama_client.py

Tiny shared wrapper around the local Ollama HTTP API. Both
entity_extraction.py and structured_intent.py need to send a prompt and
get back a JSON string, so that logic lives here once instead of being
copy-pasted in both files.

Also the one place per-call LLM timing is recorded (see _call_timings
below) -- since every LLM call in the whole pipeline already funnels
through call_ollama, this is the natural single choke point to measure
from, rather than adding timing code separately at each call site in
entity_extraction.py/structured_intent.py.
"""

import time

import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5:7b"  # must already be pulled locally: `ollama pull qwen2.5:7b`

# Module-level, not returned from call_ollama, so timing is opt-in for
# callers that want it (the eval harness) without changing call_ollama's
# return type or forcing every caller to unpack a (response, duration)
# tuple. A plain list, not per-thread/per-message keyed storage -- this
# pipeline is single-threaded end to end (one message resolved at a time,
# see run.py), so a caller just needs to reset_call_timings() before a
# message and get_call_timings() after it to get exactly that message's
# calls. Would need real thread-safety (e.g. contextvars) if this pipeline
# ever processed messages concurrently -- not the case today.
_call_timings: list[dict] = []


def reset_call_timings() -> None:
    """Clears recorded call timings. Call once per message, before
    resolve_structured_intent, so one message's timings don't include
    calls made while resolving a previous message."""
    _call_timings.clear()


def get_call_timings() -> list[dict]:
    """Returns every call_ollama timing recorded since the last
    reset_call_timings(), as [{"label": ..., "duration_ms": ...}, ...] in
    call order. A copy, not the live list, so callers can safely store or
    log this without it changing under them if another call_ollama runs
    afterward."""
    return list(_call_timings)


class OllamaUnavailableError(RuntimeError):
    """
    Raised when the local Ollama server can't be reached, times out, or
    returns an HTTP error -- e.g. Ollama isn't running, or the model
    named in MODEL was never pulled.

    Deliberately a distinct, catchable type rather than letting the raw
    requests exception propagate: this is a genuinely different situation
    from "the model ran and gave a bad answer" (which entity_extraction.py
    and structured_intent.py already handle by degrading gracefully to
    empty results) -- here nothing ran at all. A caller like a GUI needs
    to tell these apart to show "service unavailable, try again" instead
    of silently pretending nothing matched. Not caught anywhere inside
    the pipeline itself on purpose -- see notes/integration-guide.md for
    where this is meant to be caught.
    """


def call_ollama(prompt: str, timeout: int = 60, *, label: str = "unlabeled") -> str:
    """
    Sends `prompt` to the local Ollama server and returns its raw text
    response as a string.

    format="json" tells Ollama to constrain its output to valid JSON --
    this guarantees the string is parseable JSON, NOT that it matches
    whatever shape we expect (the caller still has to check that).

    temperature=0 makes output deterministic given the same input, which
    matters here because we're evaluating pipeline behavior and want
    repeatable results between runs, not creative variation.

    `label` identifies WHICH call this is for metrics purposes only (e.g.
    "entity_extraction_llm" vs "structured_intent_llm") -- purely a
    bookkeeping tag, never sent to Ollama itself. Defaults to "unlabeled"
    rather than being required, so this stays backward-compatible with any
    future call site that doesn't care about per-call timing breakdowns.
    Every call, successful or not, records one timing entry -- a timeout or
    connection failure is itself useful latency data, not something to
    hide from the metrics by only timing the happy path.
    """
    start = time.perf_counter()
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0},
            },
            timeout=timeout,
        )
        response.raise_for_status()  # raises if Ollama itself returned an HTTP error
    except requests.RequestException as exc:
        raise OllamaUnavailableError(
            f"Could not reach Ollama at {OLLAMA_URL} with model {MODEL!r} -- "
            f"is `ollama serve` running, and has the model been pulled "
            f"(`ollama pull {MODEL}`)? Underlying error: {exc}"
        ) from exc
    finally:
        # In `finally`, not just after the try block, so a timeout/connection
        # failure still gets a timing entry (with whatever elapsed before it
        # failed) instead of silently recording nothing for that call.
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        _call_timings.append({"label": label, "duration_ms": elapsed_ms})

    return response.json()["response"]
