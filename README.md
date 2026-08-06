# ChatBot — Δήμος Ηρακλείου e-Services Assistant

A virtual assistant for Heraklion municipality's e-services: a citizen types a
message in Greek, and the bot resolves what they want and answers using the
real service catalog (`data/heraklion_eservices.json`, ~167 titles scraped
from `eservices.heraklion.gr`).

The repo currently holds **two implementations** of the answering logic,
at different stages:

| | Status | Approach |
|---|---|---|
| `gui.py` + `connector.py` | **Currently wired up and running** | BERT (`dimos-intent-model/`) for intent detection → TF-IDF search over the catalog → Llama 3.1 (via Ollama) composes the answer |
| `pipeline/` | **Built, tested, not yet wired into the GUI** | Rule-based fast path + gazetteer (KB-matching) resolve intent/service without an LLM call where possible, falling back to an LLM (`qwen2.5:7b` via Ollama) only for the genuine residue; template-only answer composition (no LLM in the final answer) |

`pipeline/` is meant to eventually replace `connector.py` inside `gui.py` —
see [`notes/integration-guide.md`](notes/integration-guide.md) for exactly what that swap involves.

## Running the current GUI (`gui.py` / `connector.py`)

```bash
pip install pywebview torch transformers joblib numpy requests scikit-learn
ollama serve
ollama pull llama3.1
python3 gui.py
```

Note: `dimos-intent-model/model.safetensors` (the actual BERT weights) is
gitignored — you'll need to supply that file separately for BERT-based
intent detection to work.

## Trying the new pipeline standalone

```bash
pip install requests scikit-learn
ollama serve
ollama pull qwen2.5:7b
python3 pipeline/run.py
```

Full setup, latency notes, and known limitations are in
[`notes/integration-guide.md`](notes/integration-guide.md).

## Project layout

- `gui.py`, `connector.py` — the live desktop GUI (pywebview) and its backend.
- `pipeline/` — the new rule/gazetteer/LLM pipeline (see
  [`notes/pipeline-overview.md`](notes/pipeline-overview.md) for a file-by-file walkthrough).
- `data/` — the crawled service catalog and crawler resume state.
- `crawler_script.py`, `checker.py`, `checker_master.py`, `url_validator.py`,
  `Makefile` — tools for (re)building and validating `data/heraklion_eservices.json`.
- `dimos-intent-model/`, `prakt_train_0.ipynb`, `Expanded_Intent_Dataset_2.csv`,
  `benchmark_embeddings.py` — the BERT intent model `connector.py` uses, its
  training notebook/dataset, and a TF-IDF-vs-embeddings comparison.
- `notes/` — build history, fix-by-fix reasoning, and the GUI integration guide.
  Start with [`notes/README.md`](notes/README.md) or
  [`notes/pipeline-overview.md`](notes/pipeline-overview.md).
