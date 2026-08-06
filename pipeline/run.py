"""
run.py

Alpha 0.x test harness. Reads a message from the terminal, runs it
through the full pipeline (entity extraction -> structured intent ->
KB lookup), prints the result, and appends it to a JSONL log file.

JSONL = one JSON object per line. Chosen over a single JSON array file
because it's append-only-friendly (no need to re-read and rewrite the
whole file on every message) and safe to read back line-by-line even
while it's still growing.

run_and_log/print_result are also imported directly by run_full_eval.py
(the batch regression-suite runner) -- this is the one place the
"run one message, time it, log it, print it" logic lives. Originally
run_full_eval.py had its own near-duplicate of run_and_log; merged back
into one implementation here so the two harnesses can't quietly drift
out of sync with each other (e.g. one script's metrics format changing
without the other's).
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from answer_composition import compose_answer
from ollama_client import OllamaUnavailableError, get_call_timings, reset_call_timings
from structured_intent import resolve_structured_intent

LOG_DIR = Path(__file__).parent / "logs"
LOG_FILE = LOG_DIR / "eval_log.jsonl"


def run_and_log(text: str, **extra_fields) -> dict:
    """
    Runs one message through the pipeline, attaches a timing/metrics
    block, appends the result to disk, and returns the full record.

    `extra_fields` is merged into the record before it's written --
    e.g. run_full_eval.py passes test_category="old-regression",
    expected="..." for its labeled batch cases. Plain **kwargs rather
    than a dedicated parameter because this is metadata the pipeline
    itself knows nothing about (it's not part of resolve_structured_intent's
    output shape), purely for whoever's reading the log back later.
    """
    # reset_call_timings() BEFORE resolve_structured_intent, not after --
    # otherwise this message's LLM-call timings would still include
    # whatever the previous message left behind (ollama_client's timing
    # list persists across calls until explicitly cleared).
    reset_call_timings()
    pipeline_start = time.perf_counter()
    result = resolve_structured_intent(text)
    resolve_done = time.perf_counter()

    # compose_answer always returns something now (fix-008's four-way
    # branch covers every case, not just kb_match) -- "source" records
    # which branch produced it, so the log shows at a glance how often
    # each path is actually hit without re-deriving it from
    # intent/service/kb_match on every read.
    answer = compose_answer(result)
    compose_done = time.perf_counter()

    result["answer"] = answer["text"]
    result["answer_source"] = answer["source"]
    result.update(extra_fields)
    result["timestamp"] = datetime.now(timezone.utc).isoformat()
    # Timing breakdown for this one message -- total time end to end, the
    # split between the two real pipeline steps (compose_answer is
    # template-only, so its share should be near-zero; a real number there
    # would itself be a signal something's wrong), and every individual
    # LLM call made along the way (0, 1, or 2 -- entity extraction only
    # calls the LLM as a fallback, see entity_extraction.py). Rounded to
    # 0.1ms: this is for spotting slow outliers and cost per step, not
    # microbenchmarking, so sub-0.1ms precision isn't useful here.
    result["metrics"] = {
        "total_pipeline_ms": round((compose_done - pipeline_start) * 1000, 1),
        "resolve_structured_intent_ms": round((resolve_done - pipeline_start) * 1000, 1),
        "compose_answer_ms": round((compose_done - resolve_done) * 1000, 1),
        "llm_calls": get_call_timings(),
    }

    LOG_DIR.mkdir(exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")

    return result


def print_result(result: dict) -> None:
    """
    Shared console output format for one result: the full record as
    pretty-printed JSON, then a one-line summary (answer_source, total
    pipeline time, and the actual answer text). Used by both the
    interactive loop below and run_full_eval.py's batch loop, so a single
    message run interactively and the same message run as part of the
    eval suite look identical on screen.
    """
    print(json.dumps(result, ensure_ascii=False, indent=2))
    total_ms = result.get("metrics", {}).get("total_pipeline_ms")
    timing_note = f" ({total_ms}ms)" if total_ms is not None else ""
    print(f"\n>>> [{result['answer_source']}]{timing_note} {result['answer']}")


if __name__ == "__main__":
    print("Alpha 0.x test harness. Type a message, or 'quit' to exit.")
    while True:
        message = input("\n> ").strip()
        if message.lower() in ("quit", "exit"):
            break
        if not message:
            continue
        # Reference pattern for a GUI: OllamaUnavailableError is a distinct,
        # expected failure (service down), not a bug -- caught here so one
        # bad message doesn't kill the whole session, same reasoning a GUI
        # would need to show "try again" instead of freezing/crashing.
        try:
            output = run_and_log(message)
        except OllamaUnavailableError as exc:
            print(f"\n[Ollama unavailable] {exc}")
            continue
        print_result(output)
