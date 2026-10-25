#!/usr/bin/env python3
"""VoiceOps 2026 - official run command.

Takes a folder of customer audio files, runs the ZentroMart agent on
each, and saves for every input:
  <name>.txt   the agent's reply (text)
  <name>.wav   the agent's reply (speech, via Gnani TTS)
  <name>.json  transcript, reply, decision, retrieved section IDs, tool calls
plus a summary.json for the whole folder.

Usage:
  export GNANI_API_KEY=...                       # from app.gnani.ai/voice
  export VOICEOPS_DATA_DIR=/path/to/Capstone_Project_Dataset_FTTT_2026
  python run.py --input-dir ./customer_audio --output-dir ./outputs

Options:
  --conversation   treat the folder as ONE multi-turn conversation
                   (files in name order share the agent's memory);
                   default is one fresh agent per file.
  --text           text-only mode: skip TTS audio output (still writes
                   .txt/.json). Useful in CI without a Gnani key.
  --language       STT language code, default en-IN (English + Hindi mix).
  --voice          TTS voice, default Kaveri (timbre-v2.5).

Input files may also be .txt transcripts - handy for offline testing;
they are read as the transcript instead of running STT.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.agent import SupportAgent
from src.conversation import ConversationAgent
from src.voice import GnaniNotConfigured, VoiceAgent

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".ogg", ".flac"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--data-dir", default=os.environ.get("VOICEOPS_DATA_DIR", ""))
    ap.add_argument("--conversation", action="store_true")
    ap.add_argument("--text", action="store_true", help="skip TTS audio")
    ap.add_argument("--language", default="en-IN")
    ap.add_argument("--voice", default="Kaveri")
    args = ap.parse_args()

    if not args.data_dir or not os.path.isdir(os.path.join(args.data_dir, "kb")):
        print("ERROR: dataset not found. Set VOICEOPS_DATA_DIR to the extracted "
              "Capstone_Project_Dataset_FTTT_2026 folder (it is not part of "
              "this repo - see README).", file=sys.stderr)
        return 2
    os.makedirs(args.output_dir, exist_ok=True)

    core = SupportAgent(args.data_dir)
    conv = ConversationAgent(core) if args.conversation else None
    voice = VoiceAgent(conv or core, language_code=args.language, voice=args.voice)

    files = sorted(f for f in os.listdir(args.input_dir)
                   if os.path.splitext(f)[1].lower() in AUDIO_EXTS | {".txt"})
    if not files:
        print(f"No audio/.txt files in {args.input_dir}", file=sys.stderr)
        return 2

    summary = []
    for fname in files:
        stem = os.path.splitext(fname)[0]
        src = os.path.join(args.input_dir, fname)
        if fname.lower().endswith(".txt"):
            with open(src, encoding="utf-8") as fh:
                heard = fh.read().strip()
            handler = (conv.respond if conv else core.answer)
            res = handler(heard)
            record = {"input": fname, "transcript": heard, "reply": res.reply,
                      "decision": res.decision, "evidence": res.evidence,
                      "tool_calls": res.tool_calls, "audio_file": None}
        else:
            out_wav = os.path.join(args.output_dir, stem + ".wav")
            try:
                record = voice.voice_turn(src, output_file=out_wav)
            except GnaniNotConfigured as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 2
            record["input"] = fname
            if args.text:
                record["audio_file"] = None
                os.remove(out_wav) if os.path.exists(out_wav) else None
        with open(os.path.join(args.output_dir, stem + ".txt"), "w",
                  encoding="utf-8") as fh:
            fh.write(record["reply"])
        with open(os.path.join(args.output_dir, stem + ".json"), "w",
                  encoding="utf-8") as fh:
            json.dump(record, fh, ensure_ascii=False, indent=2)
        summary.append(record)
        print(f"{fname}: [{record['decision']}] {record['reply'][:90]}")

    with open(os.path.join(args.output_dir, "summary.json"), "w",
              encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    print(f"\n{len(summary)} file(s) processed -> {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
