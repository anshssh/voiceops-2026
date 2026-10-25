# VoiceOps 2026 — Report: ZentroMart Support Agent

## What we built

A ZentroMart customer-support agent in the four steps of the brief, as
one codebase: a grounded single-turn agent (Steps 1–2), a stateful
conversation agent using the provided mock tools (Step 3), and a Gnani
speech wrapper (Step 4). The core is pure Python standard library, so
the whole system runs and is testable with no API key except Gnani's
for live speech.

**Step 1 — Prompt-only baseline.** A system prompt casting the model as
ZentroMart's AI assistant, with no documents and no tools. Without an
LLM key it falls back to the generic answers a model gives from general
e-commerce knowledge; the scoring path is identical either way.

**Step 2 — RAG.** The 21 KB documents are chunked by section, keeping
each `[SECTION-ID]`, status and effective date. Retrieval is BM25 with
precedence boosts implementing KB-00.1 (current policy > agent guide >
help > FAQ > marketing; superseded documents down-weighted to 0.25×),
Hinglish/Hindi query expansion, and the product catalog indexed as
evidence (`products.csv:SKU`). On top of retrieval sit deterministic
solvers for the calculations the policies demand: refund timelines in
business days (Mon–Sat, skipping holidays.csv), return windows in
calendar days with the festive-sale (RET-8) and pre-August-2026
electronics (RET-3) exceptions, reverse-pickup fees, Assured warranty
with the marketplace-seller exception (MKS-3), cancellations, and
escalation/refusal rules. Uncovered topics get an honest "I don't have
information about that" plus an offer of a human.

**Step 3 — Conversation.** A state machine: introduce as AI assistant →
ask for order ID → `lookup_order` unverified → verify with phone last-4
or delivery pincode (one retry, then refuse details) → answer follow-ups
from the verified order record (status, promised date, return deadline,
refund state incl. overdue-refund escalation with RRN, repeat-contact
and human-request handovers via `create_ticket`). Topic switches are
answered without losing the order context; nothing is claimed done
unless a tool returned success.

**Step 4 — Voice.** `run.py` takes a folder of audio files, transcribes
each with Gnani STT (en-IN by default), runs the same conversation
brain, and writes reply text + Gnani TTS audio (model timbre-v2.5
named explicitly, voice Kaveri) + the retrieved section IDs per file.
An ASR-normalisation layer repairs the failure modes visible in the
practice `asr_text` column (spelled-out SKUs like "ele-zero zero one
to", split words like "re fund", spelled years).

## Evaluation (dataset's own scoring rules)

| Agent | Score |
| --- | --- |
| Step 1, prompt-only | 6 / 52 questions (11.5%) |
| Step 2, RAG + solvers | **52 / 52 (100%)**, decisions 52/52, gold-evidence hit 100% |
| Step 2 on ASR transcripts | **52 / 52** (41/52 before ASR normalisation) |
| Step 3, conversations | **96 / 96 turns (100%)**, decisions 96/96 |

Step 1 fails exactly where the brief predicts: it parrots the generic
"refunds take 5–7 days" line (wrong per payment method — REF-2 beats
FAQ-1), guesses return windows, and invents warranty answers. Grounding
plus the policy solvers removes all three failure classes on the
practice set. These are practice-set numbers; the hidden test set will
be lower, and the solvers are written as general policy rules (not
per-question answers) for that reason.

## What went wrong, and what we fixed

1. **FAQ trap:** naive retrieval answers refund questions from FAQ-1
   ("5 to 7 days"). Fixed by precedence boosts + the REF-2 solver.
2. **Superseded policy:** returns v3 (10-day electronics) outranked v4
   for old questions. Fixed with status down-weighting and the RET-3
   date rule (delivered before 1 Aug 2026 → 10 days, else 7).
3. **Hindi/Hinglish retrieval:** BM25 over English documents misses
   "वापस / लौटाने". Fixed with a concept-expansion map for retrieval
   and multilingual solver triggers.
4. **Troubleshooting vs catalog:** "speaker won't turn on" retrieved
   the speaker's product row, not TRB-4. Fixed with symptom routing.
5. **ASR numbers:** spelled-out SKUs and years broke product lookup
   and date maths (41/52 → 52/52 after normalisation). A date parser
   bug of the same family ("Fit 3 Pro… delivered on 20 July") was
   fixed by scanning all date candidates, not the first number.
6. **Hindi dates:** the checker expects "27 अक्टूबर 2026" (ASCII
   digits); our first Devanagari-digit form failed string checks.

## Live voice verification (22 Oct 2026)

Ran end-to-end against a real Gnani account (key created for this
test, revoked immediately after). Outputs in `demo/live_test/`:
TTS-synthesised customer questions → Gnani STT → agent → Gnani TTS
replies, plus spoken replies for the full Scene-1 conversation.
Real STT output differed from the practice transcripts in two ways
the practice set never showed, and both are now handled in
`normalize_asr`: dates spelled as words ("seventeenth october
twenty twenty six" → 17 October 2026, refund window computed as
24–27 October 2026) and number words inside product names
("kestrel book fourteen laptop" → Kestrel Book 14, correctly
escalated as a >₹10,000 damage case with a Priority Resolution
ticket). Practice scores after the change: Step 2 still 52/52,
conversations still 96/96.

## Limitations and next steps

- The demo video still needs the participant's own recorded voice
  for the customer lines (the live test used TTS-synthesised
  questions to verify the pipeline); the script is in
  `demo/DEMO_SCRIPT.md`.
- Retrieval is BM25; an embedding retriever behind the same interface
  is the obvious upgrade for paraphrase-heavy hidden questions.
- Answer phrasing is template-based; an optional LLM pass over the
  retrieved chunks + solver facts (key-gated) would improve fluency,
  especially in Hindi, without changing any fact.
