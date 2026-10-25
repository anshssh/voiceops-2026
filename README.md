# VoiceOps 2026 — ZentroMart Support Agent

A customer support agent for **ZentroMart** (fictional Indian grocery +
electronics store) that answers from company policy documents, holds a
verified multi-turn conversation using mock order tools, and speaks
through **Gnani STT/TTS**. Built for the VoiceOps 2026 capstone
(LLM & Generative AI Course, C&A Club IIT Guwahati × Gnani.ai).

The agent core is **pure Python 3.10+ standard library** — no LLM API
key is required to run it. Retrieval is BM25 over section-level chunks;
policy calculations (business-day refund dates, return windows, fees,
warranty) are deterministic solvers read off the policy documents;
speech is Gnani only.

## Setup

```bash
pip install -r requirements.txt          # installs gnani-vachana for voice

# 1. Get the dataset (provided separately by the organisers - NOT in this repo)
#    Extract Capstone_Project_Dataset_FTTT_2026.zip and check it:
python /path/to/Capstone_Project_Dataset_FTTT_2026/validate_dataset.py

# 2. Configure secrets (copy .env.example, or export directly)
export GNANI_API_KEY=<your key from app.gnani.ai/voice>
export VOICEOPS_DATA_DIR=/path/to/Capstone_Project_Dataset_FTTT_2026
```

## Run

```bash
# Batch mode (the official run command): a folder of customer audio in,
# reply text + reply audio + retrieved sources out, per file.
python run.py --input-dir ./customer_audio --output-dir ./outputs

# Same folder treated as ONE multi-turn conversation (shared memory):
python run.py --input-dir ./customer_audio --output-dir ./outputs --conversation

# Text-only (no TTS) / offline testing with .txt transcripts as inputs:
python run.py --input-dir ./transcripts --output-dir ./outputs --text
```

Every output folder contains, per input: `<name>.txt` (reply),
`<name>.wav` (spoken reply, unless `--text`), `<name>.json`
(transcript, reply, decision, **retrieved section IDs**, tool calls),
and a `summary.json`.

## Evaluate (Steps 1 vs 2 vs 3)

```bash
python scripts/run_evaluation.py --data-dir $VOICEOPS_DATA_DIR
```

Measured on the provided practice sets (see `report.pdf` / `report.md`):

| Agent | Practice questions (52) | Conversations (96 turns) |
| --- | --- | --- |
| Step 1 — prompt-only baseline | 6 / 52 (11.5%) | — |
| Step 2 — RAG + policy solvers | **52 / 52 (100%)** | — |
| Step 3 — conversation + tools | — | **96 / 96 (100%)** |
| Step 2 on ASR-style transcripts | **52 / 52** (41/52 before ASR normalisation) | — |

Scores use the dataset's own rules: `must_include` / `must_not_include` /
expected decision, plus gold-evidence overlap for retrieval.

## How it works

```
audio ──Gnani STT──▶ transcript ──▶ ASR normalisation ──▶ ConversationAgent
                                                              │  state: intro →
                                                              │  order ID → verify
                                                              │  (1 retry) → context
                                                              ▼
                              reply ◀── solvers + BM25 RAG over kb/ sections
                                │       (precedence: current policy > agent
                                │        guide > help > FAQ > marketing;
                                │        superseded docs down-weighted)
                                └──▶ Gnani TTS (timbre-v2.5, Kaveri) ──▶ audio
```

- `src/kb.py` — KB chunking by `[SECTION-ID]`, BM25 with precedence boosts,
  product catalog as retrievable evidence (`products.csv:SKU`).
- `src/agent.py` — single-turn grounded agent: refund timelines in business
  days (Mon–Sat excl. holidays), return windows (calendar days, festive-sale
  and pre-Aug-2026 electronics exceptions), fees, warranty/Assured with the
  marketplace exception, cancellations, escalation & refusal rules, and an
  honest "I don't have information about that" for uncovered topics.
- `src/conversation.py` — Step 3 state machine over the *provided* mock
  tools (`lookup_order` with phone-suffix/pincode verification,
  `create_ticket` confirmed only when `created=True`).
- `src/voice.py` — Gnani STT/TTS wrapper; empty-transcript recovery line;
  spoken formatting (order IDs in groups of four, dates with year).
- `src/baseline.py` — Step 1 prompt-only agent for the comparison.
- `src/evaluate.py` — scorer implementing the dataset's checking rules.

## Rules honoured

- Gnani is the only speech service used. Dates are computed against the
  dataset's fixed "today", **20 October 2026**. No real customer data —
  synthetic dataset only. No secrets in the repo (`.env.example` only).
- The agent answers from the documents; it never invents a policy, date
  or amount, and never claims an action a tool did not perform.
