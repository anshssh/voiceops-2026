"""Step 1 - prompt-only baseline.

The Step 1 agent gets the same system prompt a student would write in
Week 1-2 ('You are ZentroMart's support assistant...') but NO documents,
NO tools and NO order data. When an LLM API key is configured it calls
that LLM with only the system prompt; otherwise it falls back to the
generic prior answers a language model typically gives from general
e-commerce knowledge. Either way it is scored with exactly the same
scorer as the Step 2 agent, which is what makes the comparison honest.
"""
from __future__ import annotations

import re

from .agent import Result
from .lang_util import detect_language

SYSTEM_PROMPT = (
    "You are ZentroMart's AI support assistant. ZentroMart is an Indian online "
    "store for groceries and electronics. Answer customer questions about "
    "deliveries, returns, refunds and cancellations helpfully and briefly. "
    "Introduce yourself as an AI assistant in your first reply."
)


class PromptOnlyBaseline:
    def __init__(self):
        self.introduced = False

    def answer(self, text: str) -> Result:
        """Generic-prior fallback used when no LLM key is configured."""
        t = text.lower()
        lang = detect_language(text)
        if "refund" in t or "रिफ़ंड" in text or "रिफंड" in text:
            if "wallet" in t:
                reply = "Refunds to your wallet usually take 5 to 7 days."
            elif "upi" in t:
                reply = "UPI refunds usually take 5 to 7 days to reach your account."
            elif "card" in t:
                reply = "Card refunds usually take 5 to 7 days to reach your account."
            elif "net" in t:
                reply = "Net banking refunds usually take 5 to 7 days."
            else:
                reply = "Refunds usually take 5 to 7 working days to reach your account."
            return Result(reply, "answer", [])
        if "return" in t or "वापस" in text or "लौटा" in text:
            if "fee" in t or "charge" in t:
                reply = "Returns are usually collected free of charge."
                return Result(reply, "answer", [])
            reply = ("Most items can be returned within 10 to 15 days of delivery, "
                     "depending on the category.")
            return Result(reply, "answer", [])
        if "warranty" in t or "assured" in t:
            reply = ("The product comes with the manufacturer's standard warranty. "
                     "You can check the exact period on the product page.")
            return Result(reply, "answer", [])
        if "cancel" in t:
            reply = ("You can cancel your order from the My Orders section of the "
                     "app, as long as it has not been delivered.")
            return Result(reply, "answer", [])
        if "deliver" in t or "courier" in t:
            reply = "Delivery usually takes 3 to 5 days, and the courier will call you before arriving."
            return Result(reply, "answer", [])
        reply = ("I'm ZentroMart's AI support assistant. I can help with orders, "
                 "returns and refunds - could you share more details?")
        return Result(reply, "answer", [])
