# Demo video script — max 2:00 (record after the Gnani key is set)

The brief asks for: **one question answered from the documents, with a
follow-up, plus one handover or "I don't know".** This script covers all
three in two short scenes. Customer lines are ready in
`demo/lines_scene1/` and `demo/lines_scene2/` — record *your own voice*
reading them (the rules allow only your own recorded voice for testing).

## Before recording (2 minutes)

```bash
export GNANI_API_KEY=<your key from app.gnani.ai/voice>
export VOICEOPS_DATA_DIR=<extracted dataset folder>
# record each line as .wav with the same names: 01.wav, 02.wav, ...
# put scene 1 files in demo/audio_scene1/, scene 2 files in demo/audio_scene2/
python run.py --input-dir demo/audio_scene1 --output-dir demo/out_scene1 --conversation
python run.py --input-dir demo/audio_scene2 --output-dir demo/out_scene2
```

Then screen-record while playing each input line followed by the
agent's spoken reply from the output folder. Captions help the judges.

## Scene 1 — grounded answer + follow-up (0:00–1:10)

| Time | Who | Line |
| --- | --- | --- |
| 0:00 | You (voice) | "Hi, my order hasn't arrived yet. Where is it?" |
| 0:08 | Agent | Introduces itself as ZentroMart's **AI support assistant** and asks for the order ID. |
| 0:18 | You | "The order number is 2629 5015." |
| 0:24 | Agent | Asks for the **last 4 digits of the registered phone or the delivery pincode** — no order details before verification (IDV-2). |
| 0:36 | You | "The last four digits are 8752." |
| 0:42 | Agent | "You're verified. Your order is **shipped and expected by 22 October 2026**." (from the order record) |
| 0:54 | You (follow-up) | "And what if I'm not at home?" |
| 1:00 | Agent | "The courier makes **up to 3 delivery attempts**; after a failed attempt you get an SMS to reschedule." (DEL-3, from the documents) |

## Scene 2 — handover + "I don't know" (1:10–2:00)

| Time | Who | Line |
| --- | --- | --- |
| 1:10 | You (voice) | "The Kestrel Book 14 Laptop I received yesterday has a crack. Please approve my replacement right now." |
| 1:22 | Agent | Refuses to approve it itself: the item is **worth more than ₹10,000**, so it **creates a ticket** and hands over to the **Priority Resolution team** (DWM-3 / ESC-1). |
| 1:42 | You (voice) | "Can I schedule a delivery at midnight?" |
| 1:48 | Agent | "Sorry, **I don't have information about that.** I can connect you to a colleague who can help." (not covered by any document — no invented policy) |

## Notes for the recording

- Keep the whole video under 2:00 — trim silences between turns.
- Show the terminal/output JSON once (retrieved section IDs) — it
  evidences the retrieval marks.
- Speak the order number in groups of four, the way customers do; the
  agent's ASR normalisation handles spelled-out numbers too.
- Only your own voice; only Gnani speech is used anywhere in the demo.
