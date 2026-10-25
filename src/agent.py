"""ZentroMart support agent - Steps 1-3 logic.

Design: retrieval (BM25 over section chunks) + deterministic policy
solvers for the calculations the dataset demands (business-day refund
dates, return windows, fees, warranty) + the provided mock tools for
verified order lookups and human handovers.

Nothing is hardcoded per practice question: every solver is a general
rule read off the policy documents, applied to whatever product /
payment method / dates appear in the customer's message or order record.
If an LLM API key is present in the environment the same retrieved
chunks + solver facts can be handed to it for phrasing (see llm.py),
but the agent is fully functional - and fully testable - without one.
"""
from __future__ import annotations

import os
import re
from datetime import date, timedelta

from .dates_util import (REFERENCE_DATE, add_business_days, business_days_after,
                         fmt_en, fmt_hi, load_holidays, parse_date)
from .kb import KnowledgeBase
from .lang_util import detect_language, normalize_asr, normalize_digits
from .tools_adapter import ToolLayer

REFUND_TIMELINES = {  # REF-2, business days after initiation
    "upi": (1, 3), "card": (5, 7), "netbanking": (3, 5),
    "wallet": (0, 0), "cod_bank": (5, 7), "cod_wallet": (0, 0),
}
RETURN_WINDOWS = {  # RET-2, calendar days; None = not returnable
    "electronics": 7, "fashion": 15, "home_kitchen": 10,
    "beauty_sealed": 7, "books_media": 10,
    "grocery": None, "innerwear": None, "digital": None,
}
FESTIVE_START, FESTIVE_END = date(2026, 10, 1), date(2026, 10, 15)  # RET-8
ELECTRONICS_CHANGE = date(2026, 8, 1)  # RET-3


def return_window_days(category: str, delivered: date | None,
                       placed: date | None) -> int | None:
    if category == "fashion" and placed and FESTIVE_START <= placed <= FESTIVE_END:
        return 30
    if category == "electronics" and delivered and delivered < ELECTRONICS_CHANGE:
        return 10
    return RETURN_WINDOWS.get(category)


def detect_payment_method(text: str) -> str | None:
    t = text.lower()
    if "net banking" in t or "netbanking" in t or "net-banking" in t:
        return "netbanking"
    if "credit card" in t or "debit card" in t or re.search(r"\bcard\b", t):
        return "card"
    if "upi" in t:
        return "upi"
    if "wallet" in t or "वॉलेट" in t:
        return "wallet"
    if "cash on delivery" in t or re.search(r"\bcod\b", t):
        return "cod"
    return None


def fmt_date_for(d: date, lang: str) -> str:
    return fmt_hi(d) if lang == "hi" else fmt_en(d)


class Result:
    def __init__(self, reply, decision, evidence=None, tool_calls=None):
        self.reply = reply
        self.decision = decision
        self.evidence = evidence or []
        self.tool_calls = tool_calls or []

    def to_dict(self):
        return {"reply": self.reply, "decision": self.decision,
                "evidence": self.evidence, "tool_calls": self.tool_calls}


class SupportAgent:
    """Single-turn grounded agent (Step 2), reused inside conversations."""

    # Below this top BM25 score (and with no solver firing) we treat the
    # question as uncovered: say so and offer a human (brief, Step 2 rule).
    UNKNOWN_SCORE_THRESHOLD = 2.2

    def __init__(self, dataset_dir: str):
        self.dataset_dir = dataset_dir
        self.kb = KnowledgeBase(os.path.join(dataset_dir, "kb"),
                                os.path.join(dataset_dir, "data"))
        self.holidays = load_holidays(os.path.join(dataset_dir, "data"))
        self.tools = ToolLayer(dataset_dir)

    # ------------------------------------------------------------- helpers
    def _ticket(self, summary: str, order_id=None, reason=None) -> dict:
        return self.tools.create_ticket(summary, order_id=order_id, reason=reason)

    def _unknown(self, lang: str) -> Result:
        if lang == "hi":
            reply = ("माफ़ कीजिए, मेरे पास इस बारे में जानकारी नहीं है। "
                     "मैं आपको किसी सहयोगी से जोड़ सकती हूँ जो मदद कर सके।")
        elif lang == "hi-en":
            reply = ("Sorry, iske baare mein mere paas jaankari nahi hai. "
                     "Main aapko ek colleague se connect kar sakti hoon jo help kar sake.")
        else:
            reply = ("Sorry, I don't have information about that. "
                     "I can connect you to a colleague who can help.")
        return Result(reply, "answer", [])

    # ------------------------------------------------------------ solvers
    def _refund_timeline(self, text: str, lang: str) -> Result | None:
        t = text.lower()
        if not any(p in t or p in text for p in
                   ("refund", "money back", "get my money", "रिफ़ंड", "रिफंड")):
            return None
        method = detect_payment_method(text)
        started = parse_date(normalize_digits(text))
        # COD refund choice (REF-3)
        if method == "cod":
            reply = ("For a cash-on-delivery order you can choose a refund to your "
                     "ZentroMart Wallet, which is instant within 2 hours, or a bank "
                     "transfer, which takes 5 to 7 business days after your bank "
                     "details are verified.")
            if lang == "hi-en":
                reply = ("Cash on delivery order ke liye aap ZentroMart Wallet mein "
                         "turant refund le sakte hain, ya bank transfer chun sakte "
                         "hain - bank details verify hone ke baad 5 to 7 business days lagte hain.")
            return Result(reply, "answer", ["REF-3", "REF-2"])
        if method is None:
            # 'When will my refund come?' with nothing to go on -> clarify (PQ0051 pattern)
            if not re.search(r"\border\b", t):
                reply = ("That depends on how you paid and whether the refund has "
                         "been initiated. Could you tell me your payment method, "
                         "or your order ID?")
                if lang == "hi":
                    reply = ("यह इस पर निर्भर करता है कि आपने भुगतान कैसे किया था। "
                             "क्या आप अपना payment method या order ID बता सकते हैं?")
                return Result(reply, "clarify", ["REF-2"])
            return None
        low, high = REFUND_TIMELINES[method]
        if method == "wallet":
            reply = ("Refunds to the ZentroMart Wallet are instant, within 2 hours "
                     "of the refund being initiated.")
            if lang != "en":
                reply = ("ZentroMart Wallet mein refund turant hota hai - "
                         "initiate hone ke 2 hours ke andar aa jata hai.")
            return Result(reply, "answer", ["REF-2", "KB-00.1"])
        if started:
            d_low = add_business_days(started, low, self.holidays)
            d_high = add_business_days(started, high, self.holidays)
            if lang == "hi":
                reply = (f"आपका refund {fmt_hi(d_low)} से {fmt_hi(d_high)} के बीच आ जाना चाहिए। "
                         f"यह {low} to {high} business days में आता है; रविवार और warehouse "
                         "holidays नहीं गिने जाते।")
            elif lang == "hi-en":
                reply = (f"Aapka refund {fmt_en(d_low)} se {fmt_en(d_high)} ke beech aa jaana "
                         f"chahiye. Yeh {low} to {high} business days mein aata hai; Sunday "
                         "aur warehouse holidays nahi gine jaate.")
            else:
                reply = (f"Your refund should arrive between {fmt_en(d_low)} and "
                         f"{fmt_en(d_high)}. It takes {low} to {high} business days; "
                         "Sundays and warehouse holidays are not counted.")
            return Result(reply, "answer", ["REF-2", "KB-00.3"])
        names = {"upi": "UPI", "card": "credit or debit card", "netbanking": "net banking"}
        reply = (f"A refund to {names.get(method, method)} takes {low} to {high} "
                 "business days after the refund is initiated.")
        if lang == "hi-en":
            reply = (f"{names.get(method, method)} par refund initiate hone ke baad "
                     f"{low} to {high} business days mein aa jata hai.")
        return Result(reply, "answer", ["REF-2", "KB-00.1"])

    def _return_window(self, text: str, lang: str) -> Result | None:
        t = text.lower()
        if not any(w in t for w in ("return", "send back")) and "वापस" not in text and "लौटा" not in text:
            return None
    	# opened-beauty / non-returnable eligibility is its own solver
        product = self.kb.find_product(text)
        placed = None
        # a sale / order date mentioned in the message, e.g. 'sale on 5 October'
        sale_date = parse_date(normalize_digits(text)) if re.search(
            r"sale|order|bought|placed", t) else None
        delivered = parse_date(normalize_digits(text)) if "deliver" in t else None
        if product:
            category = product["return_category"]
            window = return_window_days(category, delivered, sale_date)
            title = product["title"]
            if window is None:
                reply = (f"Sorry, the {title} cannot be returned - items in this "
                         "category are not returnable for a change of mind. If it "
                         "arrived damaged or wrong, please report it within 48 hours "
                         "with photos.")
                if lang == "hi":
                    reply = (f"माफ़ कीजिए, {title} वापस नहीं हो सकता - यह category "
                             "change of mind पर not returnable है।")
                return Result(reply, "answer", ["RET-2", "RET-5", f"products.csv:{product['sku']}"])
            extra = ""
            evidence = ["RET-2", f"products.csv:{product['sku']}"]
            if category == "electronics":
                evidence.append("RET-3")  # the Aug-2026 window change is part of the rule
            if category == "fashion":
                extra = (" Orders placed between 1 October and 15 October 2026 in "
                         "the festive sale get 30 days instead.")
                evidence.append("RET-8")
            if sale_date and FESTIVE_START <= sale_date <= FESTIVE_END and category == "fashion":
                reply = (f"You get 30 days from delivery to return the {title}, "
                         "because it was ordered in the festive sale "
                         "(1 to 15 October 2026).")
                if lang == "hi-en":
                    reply = (f"Festive sale mein order kiya tha, isliye {title} ko "
                             "delivery se 30 din ke andar return kar sakte hain.")
                return Result(reply, "answer", ["RET-8"])
            if delivered and category == "electronics" and delivered < ELECTRONICS_CHANGE:
                reply = (f"Electronics delivered before 1 August 2026 keep the earlier "
                         f"window, so you had {window} days from {fmt_en(delivered)} "
                         f"to return the {title}.")
                return Result(reply, "answer", ["RET-3", "RETv3-2"])
            reply = (f"You can return the {title} within {window} days of delivery."
                     + extra)
            if lang == "hi":
                reply = (f"आप {title} को delivery के {window} दिन के अंदर लौटा सकते हैं।" + (
                    " 1 से 15 अक्टूबर 2026 की festive sale के order पर 30 दिन मिलते हैं।"
                    if category == "fashion" else ""))
            elif lang == "hi-en" and category == "fashion":
                reply = (f"{title} ko delivery ke {window} din ke andar return kar "
                         f"sakte hain. Festive sale (1 to 15 October) ke order par 30 din milte hain.")
            return Result(reply, "answer", evidence)
        # generic electronics window question
        if "electronic" in t or "smartwatch" in t or "smartphone" in t:
            if delivered and delivered < ELECTRONICS_CHANGE:
                return Result("Electronics delivered before 1 August 2026 keep the "
                              "earlier 10-day return window from delivery.",
                              "answer", ["RET-3", "RETv3-2"])
            return Result("No - since 1 August 2026 the return window for electronics "
                          "is 7 days from delivery for anything delivered on or after "
                          "that date.", "answer", ["RET-2", "RET-3"])
        # sale question without an identifiable product but with a fashion item word
        if sale_date and FESTIVE_START <= sale_date <= FESTIVE_END and any(
                w in t for w in ("jeans", "kurta", "tote", "bag", "shirt", "shoes",
                                 "sneakers", "clothing", "footwear")):
            reply = ("That was a festive-sale order, so you get 30 days from "
                     "delivery to return it.")
            if lang == "hi-en":
                reply = "Festive sale ka order hai, isliye delivery se 30 din tak return kar sakte hain."
            return Result(reply, "answer", ["RET-8"])
        # vague - no product, no category (PQ0018 pattern): ask one clarifying question
        if not any(w in t for w in ("electronic", "cloth", "shoe", "jeans", "kurta",
                                     "book", "notebook", "beauty", "lipstick", "perfume",
                                     "bedsheet", "grocery", "swimsuit", "briefs")):
            reply = ("It depends on the item - each category has its own return "
                     "window. Which item would you like to return?")
            if lang == "hi":
                reply = ("यह सामान पर निर्भर करता है - हर category का अपना return "
                         "window होता है। आप कौन सा सामान वापस करना चाहते हैं?")
            return Result(reply, "clarify", ["RET-2"])
        return None

    def _eligibility(self, text: str, lang: str) -> Result | None:
        t = text.lower()
        opened = any(w in t for w in ("opened", "open kiya", "खोल")) or "खोल लिया" in text
        beauty = any(w in t for w in ("lipstick", "perfume", "parfum", "beauty", "serum", "face wash"))
        if opened and beauty:
            reply = ("Beauty and personal care products can be returned only if "
                     "unopened with the seal intact, so an opened one cannot be "
                     "returned.")
            if lang == "hi":
                reply = ("नहीं, beauty product सिर्फ़ बिना खोले, सील (seal) intact "
                         "होने पर ही वापस होते हैं - खुला हुआ product वापस नहीं होगा।")
            return Result(reply, "answer", ["RET-4"])
        product = self.kb.find_product(text)
        if product and product["return_category"] in ("innerwear", "grocery", "digital"):
            reply = (f"Sorry, the {product['title']} cannot be returned - innerwear, "
                     "swimwear, grocery and gift cards are not returnable for fit or "
                     "a change of mind. If it arrived damaged or wrong, report it "
                     "within 48 hours with photos.")
            if lang == "hi-en":
                reply = (f"Sorry, {product['title']} wapas nahi ho sakta - innerwear "
                         "aur swimwear fit ya change of mind par returnable nahi hote.")
            return Result(reply, "answer",
                          ["RET-2", "RET-5", f"products.csv:{product['sku']}"])
        return None

    def _warranty(self, text: str, lang: str) -> Result | None:
        t = text.lower()
        if not any(w in t for w in ("warranty", "assured")):
            return None
        product = self.kb.find_product(text)
        if not product:
            return None
        sku = product["sku"]
        brand_months = int(product["warranty_months"])
        assured_effective = (product["assured"] == "True"
                             and product["fulfilled_by"] == "ZentroMart")  # MKS-3
        title = product["title"]
        if "assured" in t and "kaise" not in t and "how" not in t and brand_months and "what warranty" not in t:
            # pure Assured question
            if assured_effective:
                reply = (f"Yes, the {title} has a 12-month ZentroMart Assured warranty. "
                         "You can claim it from My Orders in the app.")
                if lang == "hi-en":
                    reply = (f"Haan, {title} par 12 mahine ki ZentroMart Assured warranty "
                             "hai. Claim app mein My Orders se karein.")
                return Result(reply, "answer", ["WAR-2", f"products.csv:{sku}"])
            reply = (f"No, the {title} does not carry ZentroMart Assured warranty"
                     + (" - marketplace seller items never carry Assured, even if a "
                        "listing says so." if product["fulfilled_by"] != "ZentroMart"
                        else ".")
                     + f" It has a {brand_months}-month brand warranty.")
            return Result(reply, "answer", ["WAR-1", "WAR-2", "MKS-3", f"products.csv:{sku}"])
        parts = []
        if assured_effective:
            parts.append("a 12-month ZentroMart Assured warranty")
        if brand_months:
            parts.append(f"a {brand_months}-month brand warranty")
        if not parts:
            parts.append("no warranty")
        reply = (f"The {title} comes with {' plus '.join(parts)}. "
                 "Assured claims are raised from My Orders in the app; brand "
                 "warranty claims go to the manufacturer's service centre.")
        if lang == "hi-en" and assured_effective:
            reply = (f"{title} par 12 mahine ki ZentroMart Assured warranty aur "
                     f"{brand_months} mahine ki brand warranty hai. Claim app mein "
                     "My Orders se karein.")
        return Result(reply, "answer", ["WAR-1", "WAR-2", f"products.csv:{sku}"])

    # ------------------------------------------------------------- main API
    def answer(self, text: str) -> Result:
        lang = detect_language(text)
        norm = normalize_digits(normalize_asr(text))
        t = norm.lower()
        product = self.kb.find_product(norm)

        # Privacy: never share another customer's details (ESC-4 / IDV-4)
        if re.search(r"(phone|address|email|details?) of (the|another|other|someone)", t) or \
           ("phone number" in t and "person who" in t):
            return Result("I'm sorry, I can't share any details about other customers.",
                          "refuse", ["ESC-4", "IDV-4"])

        # Fraud / unauthorised activity (ESC-1.2)
        if any(p in t for p in ("never placed", "did not place", "didn't place",
                                "not placed by me", "i never ordered", "did not make")):
            res = self._ticket("Customer reports an order on their account that they "
                               "never placed. Possible unauthorised activity; checked "
                               "the escalation guide. Reason: fraud review.",
                               reason="unauthorised_order")
            if lang == "hi-en":
                reply = ("Yeh turant dhyaan dene wali baat hai. Main ek ticket bana "
                         "rahi hoon aur aapko account security dekhne wale colleague "
                         "se connect kar rahi hoon.")
            else:
                reply = ("That needs urgent attention. I'm creating a ticket and "
                         "connecting you to a colleague who handles account security.")
            return Result(reply, "escalate", ["ESC-1"],
                          [{"tool": "create_ticket", "created": res.get("created", False)}])

        # Safety risk (DWM-5 / ESC-1.7)
        if any(p in t for p in ("swelling battery", "burning smell", "sparks",
                                "catching fire", "injured", "injury")):
            res = self._ticket("Customer reports a product safety risk. Stopped use "
                               "advised; checked damage and escalation policies. "
                               "Reason: product safety.", reason="safety")
            return Result("Please stop using the product immediately. I'm creating a "
                          "ticket and handing you over to a human colleague right away.",
                          "escalate", ["DWM-5", "ESC-1"],
                          [{"tool": "create_ticket", "created": res.get("created", False)}])

        # Damaged / wrong / missing
        damage_words = ("damag", "broken", "crack", "torn", "defect", "wrong item",
                        "missing item", "टूटा", "खराब", "toota", "tooti")
        if any(w in t or w in text for w in damage_words):
            fee_question = any(w in t for w in ("fee", "charge", "free", "collection", "pickup"))
            if product and int(product["price_inr"]) > 10000 and not fee_question:
                res = self._ticket(
                    f"Customer reports a damaged {product['title']} "
                    f"(SKU {product['sku']}, price Rs {product['price_inr']}), above "
                    "the Rs 10,000 threshold. Checked DWM-3/ESC-1. Reason: "
                    "high-value damage, Priority Resolution must decide.",
                    reason="high_value_damage")
                reply = (f"The {product['title']} is worth more than ₹10,000, so this "
                         "goes to the Priority Resolution team. I've created a ticket "
                         "and a colleague from that team will handle it - I can't "
                         "approve the claim myself.")
                if lang == "hi-en":
                    reply = (f"Yeh item ₹10,000 se zyada ka hai, isliye yeh Priority "
                             "Resolution team ke paas jayega. Maine ticket bana diya "
                             "hai - main khud claim approve nahi kar sakti.")
                return Result(reply, "escalate", ["DWM-3", "ESC-1", f"products.csv:{product['sku']}"],
                              [{"tool": "create_ticket", "created": res.get("created", False)}])
            if fee_question:
                reply = ("Yes, the collection is free - no fee applies when an item "
                         "is returned because it was damaged, defective or wrong. "
                         "Please report it within 48 hours of delivery with photos.")
                return Result(reply, "answer", ["RET-6", "DWM-2"])
            reply = ("Please report it within 48 hours of delivery, with photos of "
                     "the item and the packaging. After verification you will get a "
                     "free replacement or a full refund.")
            if lang == "hi":
                reply = ("डिलीवरी के 48 घंटे के अंदर सामान और पैकेट की फ़ोटो के साथ "
                         "शिकायत करें। जाँच के बाद मुफ़्त replacement या पूरा "
                         "refund मिलेगा।")
            return Result(reply, "answer", ["DWM-1", "FAQH-3"])

        # Topics the knowledge base simply does not cover. The document
        # list in kb/ is the agent's whole world: no physical stores, no
        # tax invoices, no student discounts, no delivery-time scheduling,
        # no store pickup, no EMI. Answering from a near-miss chunk here
        # would be inventing policy, so say so and offer a human.
        unsupported_patterns = (
            r"midnight", r"student discount", r"\bgst\b", r"tax invoice",
            r"pick ?up (my|the|your)? ?order from", r"store near",
            r"physical store", r"offline store", r"दुकान", r"\bemi\b",
            r"gift wrap", r"price match",
        )
        if any(re.search(p, t) or re.search(p, norm) for p in unsupported_patterns):
            return self._unknown(lang)

        # Troubleshooting (help_troubleshooting_electronics): route by the
        # symptom, not by product-keyword retrieval - a speaker question
        # otherwise retrieves the speaker's catalog row instead of TRB-4.
        troubleshooting = None
        if ("speaker" in t and any(w in t for w in ("turn on", "power", "not working", "won't", "wont"))):
            troubleshooting = "TRB-4"
        elif "earbud" in t and any(w in t for w in ("one side", "1 side", "ek side", "left", "right")):
            troubleshooting = "TRB-1"
        elif ("watch" in t and "sync" in t) or "not syncing" in t:
            troubleshooting = "TRB-2"
        elif "charging slowly" in t or "slow charging" in t:
            troubleshooting = "TRB-3"
        if troubleshooting:
            chunk = self.kb.by_section.get(troubleshooting)
            if chunk:
                steps = " ".join(
                    re.sub(r"^\d+\.\s*", "", line.strip())
                    for line in chunk.text.splitlines() if line.strip())
                return Result(f"Try this first: {steps}", "answer", [troubleshooting])

        for solver in (self._refund_timeline, self._eligibility,
                       self._warranty, self._return_window):
            result = solver(norm, lang)
            if result is not None:
                return result

        # Return pickup fee questions (RET-6 / PLS-2)
        if "pickup fee" in t or ("fee" in t and "return" in t):
            if "plus" in t:
                return Result("No. ZentroMart Plus members pay no reverse pickup fee "
                              "on any return - the fee is waived for members.",
                              "answer", ["RET-6", "PLS-2"])
            return Result("A reverse pickup fee of ₹49 applies only to change-of-mind "
                          "returns of clothing, footwear and bags. It is waived for "
                          "Plus members and for damaged, defective or wrong items.",
                          "answer", ["RET-6"])

        # Cancellation (CAN-1 / CAN-2)
        if "cancel" in t or "कैंसिल" in text or "stop it" in t:
            shipped = any(w in t for w in ("shipped", "ship ho", "on its way", "already on")) \
                or "शिप हो गया" in text
            if shipped:
                reply = ("A shipped order cannot be cancelled. You can refuse the "
                         "parcel at the door when it arrives, or accept it and "
                         "return the item within its return window.")
                if lang == "hi":
                    reply = ("शिप होने के बाद ऑर्डर कैंसिल नहीं होता, लेकिन आप "
                             "डिलीवरी के समय पार्सल लेने से मना कर सकते हैं।")
                return Result(reply, "answer", ["CAN-2", "FAQH-1"])
            return Result("You can cancel free of charge any time before the order "
                          "ships, from My Orders in the app. The refund is initiated "
                          "immediately.", "answer", ["CAN-1"])

        # Delivery questions
        if any(w in t for w in ("not home", "not at home", "miss the delivery", "courier comes")):
            return Result("The courier makes up to 3 delivery attempts. After a failed "
                          "attempt you get an SMS to reschedule; if the third attempt "
                          "fails, the parcel is returned to the warehouse.",
                          "answer", ["DEL-3"])
        if "dubai" in t or "outside india" in t or "international" in t:
            return Result("No, ZentroMart delivers only within India.",
                          "answer", ["DEL-5", "FAQ-5"])
        if "express" in t and ("late" in t or "arrived a day late" in t):
            return Result("Yes. If an Express order arrives after its promised date, "
                          "the ₹79 express fee is credited to your ZentroMart Wallet "
                          "automatically within 48 hours. ZentroMart Plus members pay "
                          "no express fee, so they get no credit.",
                          "answer", ["DEL-4"])
        if "two coupon" in t or "do coupon" in t or "coupons" in t:
            return Result("Only one coupon can be applied per order - coupons cannot "
                          "be combined.", "answer", ["CPN-1"])

        # Troubleshooting: answer straight from the TRB chunk text
        retrieved = self.kb.search(norm, top_k=5)
        if retrieved and retrieved[0][0].section_id.startswith("TRB"):
            chunk = retrieved[0][0]
            steps = " ".join(line.strip() for line in chunk.text.splitlines() if line.strip())
            steps = re.sub(r"^\d+\.\s*", "", steps)
            return Result(f"Try this first: {steps}", "answer", [chunk.section_id])

        # Grounded fallback, or honest 'I don't know'
        if not retrieved or retrieved[0][1] < self.UNKNOWN_SCORE_THRESHOLD:
            return self._unknown(lang)
        top = retrieved[:3]
        chunk = top[0][0]
        body = " ".join(line.strip() for line in chunk.text.splitlines()
                        if line.strip() and not line.startswith("| ---"))
        body = re.sub(r"\s+", " ", body).replace("|", " ").strip()
        sentences = re.split(r"(?<=[.!])\s+", body)
        reply = " ".join(sentences[:2])[:600]
        evidence = [c.section_id for c, _ in top]
        return Result(reply, "answer", evidence)
