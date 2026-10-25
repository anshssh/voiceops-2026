"""Step 4 - voice layer with Gnani STT/TTS (the only speech services used).

Setup (from the brief):
  1. Create a Gnani account + API key at app.gnani.ai/voice
  2. export GNANI_API_KEY=...        (never hardcode it, never commit it)
  3. pip install gnani-vachana

The agent's brain does not change: audio -> Gnani STT -> ConversationAgent
-> reply text -> Gnani TTS -> audio. TTS model is always named explicitly
(the SDK's older default is no longer served): timbre-v2.5, voice Kaveri.
"""
from __future__ import annotations

import os
import re

from .dates_util import spoken_order_id

DEFAULT_TTS_MODEL = "timbre-v2.5"   # brief: always name the model
DEFAULT_VOICE = "Kaveri"            # English voice, timbre-v2.5 catalog
DEFAULT_LANGUAGE = "en-IN"          # accepts English mixed with Hindi


class GnaniNotConfigured(RuntimeError):
    pass


def _load_clients():
    if not os.environ.get("GNANI_API_KEY"):
        raise GnaniNotConfigured(
            "GNANI_API_KEY is not set. Create a key at app.gnani.ai/voice "
            "and export it - see .env.example.")
    try:
        from gnani.stt import GnaniSTTClient
        from gnani.tts import GnaniTTSClient
    except ImportError as exc:
        raise GnaniNotConfigured(
            "gnani-vachana is not installed. Run: pip install gnani-vachana") from exc
    return GnaniSTTClient(), GnaniTTSClient()  # both read GNANI_API_KEY


def spoken_text(reply: str) -> str:
    """Make a written reply safe for the ear (STY-3): group order IDs in
    fours, spell the rupee sign out, keep the year in dates (already in
    the reply text), keep sentences short."""
    out = re.sub(r"(?<!\d)(\d{8})(?!\d)",
                 lambda m: spoken_order_id(m.group(1)), reply)
    out = out.replace("₹", "Rs ")
    return out


class VoiceAgent:
    """Wraps any agent object exposing .answer(text) or .respond(text)."""

    def __init__(self, agent, language_code: str = DEFAULT_LANGUAGE,
                 voice: str = DEFAULT_VOICE, tts_model: str = DEFAULT_TTS_MODEL):
        self.agent = agent
        self.language_code = language_code
        self.voice = voice
        self.tts_model = tts_model
        self._stt = self._tts = None

    def _clients(self):
        if self._stt is None:
            self._stt, self._tts = _load_clients()
        return self._stt, self._tts

    def transcribe(self, audio_path: str) -> str:
        stt, _ = self._clients()
        result = stt.transcribe(audio_path, language_code=self.language_code)
        return (result or {}).get("transcript", "").strip()

    def speak(self, text: str, output_file: str) -> str:
        _, tts = self._clients()
        tts.synthesize(spoken_text(text), voice=self.voice,
                       model=self.tts_model, language="en-IN",
                       output_file=output_file)
        return output_file

    def voice_turn(self, audio_path: str, output_file: str = "reply.wav") -> dict:
        """One full spoken turn: returns {transcript, reply, audio_file, ...}."""
        heard = self.transcribe(audio_path)
        if not heard:
            reply = "Sorry, I didn't catch that. Could you say it again?"
            evidence, decision, tool_calls = [], "clarify", []
        else:
            handler = getattr(self.agent, "respond", None) or self.agent.answer
            res = handler(heard)
            reply, evidence = res.reply, res.evidence
            decision, tool_calls = res.decision, res.tool_calls
        audio = self.speak(reply, output_file)
        return {"transcript": heard, "reply": reply, "audio_file": audio,
                "decision": decision, "evidence": evidence,
                "tool_calls": tool_calls}
