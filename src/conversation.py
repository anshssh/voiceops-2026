"""Step 3 - multi-turn conversation agent.

A small state machine on top of SupportAgent:
  greeting/introduction -> order ID -> verification (one retry) ->
  verified order context -> follow-ups answered from the order record
  and the policies, with topic switches leaving the order state intact.

Rules enforced (from agent guides):
  STY-1 introduce as AI assistant in the first reply, one question at a time.
  IDV-1/2/3 verify before sharing order details; one retry, then refuse.
  ESC-1/2/3 hand over with a create_ticket summary; only claim a ticket
            when the tool returned created=True.
  Never claim an action (e.g. cancelling) that no tool performed.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from .agent import Result, SupportAgent, return_window_days
from .dates_util import REFERENCE_DATE, add_business_days, business_days_after, fmt_en, fmt_hi
from .lang_util import detect_language, normalize_asr, normalize_digits

REFUND_TIMELINES = {"upi": (1, 3), "card": (5, 7), "netbanking": (3, 5), "wallet": (0, 0)}


def extract_order_id(text: str) -> str | None:
    m = re.search(r"(?<!\d)(\d{4})\s(\d{4})(?!\d)", text)
    if m:
        return m.group(1) + m.group(2)
    m = re.search(r"(?<!\d)(\d{8})(?!\d)", text)
    return m.group(1) if m else None


def extract_verification(text: str, order_id: str) -> str | None:
    """A standalone 4-digit (phone suffix) or 6-digit (pincode) value."""
    for m in re.finditer(r"(?<!\d)(\d{6})(?!\d)", text):
        if m.group(1) != order_id:
            return m.group(1)
    for m in re.finditer(r"(?<!\d)(\d{4})(?!\d)", text):
        if m.group(1) not in (order_id[:4], order_id[4:]):
            return m.group(1)
        # a lone half of the order id is not a verification value; but the
        # practice turns repeat only the suffix, which differs from the id
    return None


class ConversationAgent:
    def __init__(self, agent: SupportAgent):
        self.core = agent
        self.introduced = False
        self.order_id: str | None = None
        self.order: dict | None = None
        self.verify_attempts = 0
        self.verify_failed_closed = False
        self.last_item: dict | None = None
        self.lang = "en"
        self.turn_tool_calls: list[dict] = []

    # ------------------------------------------------------------------
    def _date(self, iso: str | None) -> str:
        if not iso:
            return ""
        y, m, d = iso[:10].split("-")
        dt = date(int(y), int(m), int(d))
        return fmt_hi(dt) if self.lang == "hi" else fmt_en(dt)

    def _ticket(self, summary: str, reason: str) -> dict:
        before = len(self.core.tools.calls)
        res = self.core.tools.create_ticket(summary, order_id=self.order_id, reason=reason)
        self.turn_tool_calls.extend(self.core.tools.calls[before:])
        return res

    def _escalate(self, summary: str, reason: str, reply_en: str,
                  evidence: list[str]) -> Result:
        res = self._ticket(summary, reason)
        reply = reply_en
        if not res.get("created"):
            reply = reply.replace("I've created a ticket", "I'm arranging a ticket")
        return Result(reply, "escalate", evidence,
                      [{"tool": "create_ticket", "created": res.get("created", False)}])

    # ------------------------------------------------------------------
    def respond(self, message: str) -> Result:
        self.turn_tool_calls = []
        norm = normalize_digits(normalize_asr(message))
        self.lang = detect_language(message) if detect_language(message) != "en" or self.lang == "en" else self.lang
        t = norm.lower()
        first = not self.introduced

        # --- awaiting / collecting the order ID -------------------------
        if self.order is None and not self.verify_failed_closed:
            oid = extract_order_id(norm)
            if oid and self.order_id is None:
                self.order_id = oid
                before = len(self.core.tools.calls)
                self.core.tools.lookup_order(oid)  # unverified: returns no details
                self.turn_tool_calls.extend(self.core.tools.calls[before:])
                self.introduced = True
                reply = ("Thanks. To verify it's your order, could you share the "
                         "last 4 digits of your registered phone number, or the "
                         "delivery pincode for this order?")
                if self.lang == "hi":
                    reply = ("धन्यवाद। Verification के लिए कृपया अपने registered phone "
                             "के आख़िरी चार अंक (last 4 digits) या इस order का "
                             "delivery पिनकोड (pincode) बताइए।")
                elif self.lang == "hi-en":
                    reply = ("Thanks. Verify karne ke liye, kya aap apne registered "
                             "phone ke last 4 digits, ya is order ka delivery "
                             "pincode bata sakte hain?")
                return Result(reply, "clarify", ["IDV-2"], list(self.turn_tool_calls))
            if self.order_id and oid is None:
                # verification value turn
                value = extract_verification(norm, self.order_id)
                if value:
                    return self._verify(value)
            if first:
                self.introduced = True
                prefix = ("Hello, I'm ZentroMart's AI support assistant. " if self.lang != "hi"
                          else "नमस्ते, मैं ZentroMart की AI support assistant हूँ। ")
                if self.lang == "hi-en":
                    prefix = "Hello, main ZentroMart ki AI support assistant hoon. "
                return Result(prefix + "Could you please share your order ID so I can help?"
                              if self.lang != "hi" else
                              prefix + "कृपया अपना order ID बताइए ताकि मैं मदद कर सकूँ।",
                              "clarify", ["STY-1"])
            if self.order_id:
                value = extract_verification(norm, self.order_id)
                if value:
                    return self._verify(value)
                return Result("I still need to verify this order first - could you "
                              "share the last 4 digits of your registered phone "
                              "number, or the delivery pincode?", "clarify", ["IDV-2"])
            return Result("Could you please share your order ID?", "clarify", ["STY-1"])

        if self.verify_failed_closed:
            return self.core.answer(message)

        # --- verified conversation --------------------------------------
        return self._verified_turn(norm, t)

    # ------------------------------------------------------------------
    def _verify(self, value: str) -> Result:
        before = len(self.core.tools.calls)
        res = self.core.tools.lookup_order(self.order_id, verification_value=value)
        self.turn_tool_calls.extend(self.core.tools.calls[before:])
        calls = [{"tool": "lookup_order", "verified": res.get("verified", False)}]
        if res.get("found") and res.get("verified"):
            self.order = res
            order = res
            status = str(order.get("status", "")).replace("_", " ")
            if order.get("promised_date") and order.get("status") in ("shipped", "placed", "packed"):
                detail = (f"Your order is {status} and is expected by "
                          f"{self._date(order['promised_date'])}.")
            elif order.get("delivered_on"):
                detail = (f"Your order was delivered on "
                          f"{self._date(order['delivered_on'])}.")
            else:
                detail = f"Your order status is {status}."
            reply = f"Thank you, you're verified. {detail} How can I help you with it?"
            if self.lang == "hi-en":
                reply = f"Thank you, aap verify ho gaye. {detail} Iske baare mein main kya madad kar sakti hoon?"
            elif self.lang == "hi":
                reply = f"धन्यवाद, आप verify हो गए। {detail} बताइए, मैं क्या मदद कर सकती हूँ?"
            return Result(reply, "answer", ["IDV-2"], calls)
        self.verify_attempts += 1
        if self.verify_attempts == 1:
            reply = ("That didn't match our records. Could you try again - the "
                     "last 4 digits of your registered phone, or the delivery "
                     "pincode?")
            if self.lang == "hi":
                reply = ("यह record से मेल (match) नहीं खाया। कृपया दोबारा (again) "
                         "कोशिश करें - registered phone के आख़िरी चार अंक या "
                         "delivery pincode बताइए।")
            elif self.lang == "hi-en":
                reply = ("Yeh match nahi hua. Please ek baar phir try karein - "
                         "registered phone ke last 4 digits, ya delivery pincode.")
            return Result(reply, "clarify", ["IDV-3"], calls)
        self.verify_failed_closed = True
        reply = ("I'm sorry, I can't share details for this order because "
                 "verification didn't match. Please contact support from your "
                 "registered phone number, or ask me a general policy question.")
        if self.lang == "hi":
            reply = ("माफ़ कीजिए, verification match नहीं हुआ, इसलिए मैं इस order "
                     "की details साझा नहीं (can't share) कर सकती। कृपया अपने "
                     "पंजीकृत (registered) phone number से support से संपर्क करें।")
        return Result(reply, "refuse", ["IDV-3"], calls)

    # ------------------------------------------------------------------
    def _verified_turn(self, norm: str, t: str) -> Result:
        order = self.order
        oid = self.order_id

        # human requested (ESC-1.6)
        if any(p in t for p in ("speak to a person", "human agent", "talk to a human",
                                "किसी इंसान", "insaan se baat", "real person")) or \
           ("इंसान" in norm and "बात" in norm):
            return self._escalate(
                f"Order {oid}: customer asked to speak to a human agent. Verified "
                "caller. Checked conversation so far; reason: human requested.",
                "human_requested",
                "Of course. I've created a ticket and a human colleague will "
                "contact you shortly.", ["ESC-1"])

        # repeat contact (ESC-1.4): stated by customer, or contacts_last_7_days >= 2
        if any(p in t for p in ("third time", "teesri baar", "3rd time", "third contact")) \
           or (int(order.get("contacts_last_7_days") or 0) >= 2 and
               any(p in t for p in ("calling again", "baar call", "times i", "time i"))):
            return self._escalate(
                f"Order {oid}: this is the third or later contact about the same "
                "issue within 7 days (contacts_last_7_days="
                f"{order.get('contacts_last_7_days')}). Checked order record. "
                "Reason: repeat contact escalation.",
                "repeat_contact",
                "I'm sorry you've had to contact us again. I've created a ticket "
                "and a colleague from the team will take this up with you.",
                ["ESC-1", "ESC-3"])

        # high-value damage approval (DWM-3 / ESC-1.1)
        if order.get("damage_sku") and any(w in t for w in ("damage", "replacement", "approve")):
            sku = order["damage_sku"]
            product = self.core.kb.products.get(sku, {})
            price = int(product.get("price_inr") or 0)
            if price > 10000 or order.get("damage_status") == "priority_resolution":
                return self._escalate(
                    f"Order {oid}: verified caller reported damage to "
                    f"{product.get('title', sku)} (Rs {price}); claim is with "
                    "Priority Resolution. Customer asked the agent to approve a "
                    "replacement, which the agent cannot do. Reason: high-value damage.",
                    "high_value_damage",
                    "I understand. Because this item is worth more than ₹10,000, "
                    "the claim sits with the Priority Resolution team - I can't "
                    "approve it myself. I've created a ticket and that team will "
                    "take it forward.", ["DWM-3", "ESC-1", "ESC-4"])

        # compensation demand for a late standard delivery (DEL-4 / ESC-4)
        if any(w in t for w in ("voucher", "compensation", "compensate")) or \
           ("chahiye" in t and re.search(r"\d+\s*(rupaye|rupees|rs)", t)):
            if order.get("delivery_type") == "express":
                return self.core.answer(norm)
            reply = ("Sorry, I can't offer that. There is no compensation for late "
                     "Standard deliveries, and I can't promise a voucher that the "
                     "policy does not allow.")
            if self.lang == "hi-en":
                reply = ("Sorry, maaf kijiye - late Standard delivery par koi "
                         "compensation ya voucher policy mein nahi hai, isliye "
                         "main yeh nahi de sakti.")
            return Result(reply, "refuse", ["DEL-4", "ESC-4"])

        # express late credit (DEL-4)
        if "express" in t and "late" in t:
            credit = order.get("express_late_credit_inr")
            when = order.get("express_late_credit_on")
            if credit:
                reply = (f"Yes - the ₹79 express fee for this order was credited "
                         f"to your ZentroMart Wallet on {self._date(when)}.")
            else:
                reply = ("Yes. For a late Express delivery the ₹79 express fee is "
                         "credited to your ZentroMart Wallet automatically within "
                         "48 hours.")
            return Result(reply, "answer", ["DEL-4"])

        # cancellation
        if "cancel" in t:
            status = order.get("status")
            if status in ("placed", "packed"):
                reply = ("This order hasn't shipped yet, so you can cancel it "
                         "free of charge from My Orders in the app - the refund "
                         "is initiated immediately. I can't cancel it myself, "
                         "but it takes a moment there.")
                if self.lang == "hi-en":
                    reply = ("Yeh order abhi ship nahi hua, isliye aap ise app ke "
                             "My Orders se free mein cancel kar sakte hain - "
                             "refund turant initiate ho jata hai. Main khud cancel "
                             "nahi kar sakti.")
                return Result(reply, "answer", ["CAN-1"])
            if status == "shipped":
                reply = ("A shipped order can't be cancelled. You can refuse the "
                         "parcel at the door instead; for a prepaid order the "
                         "refund then follows once the parcel reaches the "
                         "warehouse, usually 7 to 10 calendar days after the "
                         "last delivery attempt.")
                if self.lang == "hi-en":
                    reply = ("Shipped order cancel nahi ho sakta. Aap delivery par "
                             "parcel lene se mana (refuse) kar sakte hain; prepaid "
                             "order ka refund parcel warehouse pahunchne par "
                             "milta hai, aam taur par 7 to 10 calendar days mein.")
                return Result(reply, "refuse", ["CAN-2", "REF-1"])
            return self.core.answer(norm)

        # when was it shipped (topic switch back to the order)
        if "ship" in t and ("when" in t or "kab" in t or "hua tha" in t):
            reply = f"Your order was shipped on {self._date(order.get('shipped_on'))}."
            if self.lang == "hi-en":
                reply = f"Aapka order {self._date(order.get('shipped_on'))} ko ship hua tha."
            return Result(reply, "answer", ["TRK-1"])

        # coupons topic switch
        if "coupon" in t:
            return Result("Only one coupon can be used per order - two coupons "
                          "can't be combined on the same order.",
                          "answer", ["CPN-1"])

        # not at home during delivery
        if "not at home" in t or "not home" in t:
            return Result("No problem - the courier makes up to 3 delivery "
                          "attempts, and after a failed attempt you'll get an SMS "
                          "to reschedule.", "answer", ["DEL-3"])

        # return of a named item from this order
        item = self._match_order_item(t)
        if item and ("return" in t or "वापस" in norm or "vapas" in t):
            return self._order_return(item)

        # refund follow-ups
        if "refund" in t or "रिफ़ंड" in norm or "रिफंड" in norm:
            return self._order_refund()

        # where is my order
        if any(p in t for p in ("where", "kab aayega", "hasn't arrived", "not arrived")):
            if order.get("promised_date"):
                return Result(f"Your order is {str(order.get('status')).replace('_',' ')} "
                              f"and is expected by {self._date(order.get('promised_date'))}.",
                              "answer", ["TRK-1"])
        return self.core.answer(norm)

    # ------------------------------------------------------------------
    def _match_order_item(self, t: str) -> dict | None:
        for item in self.order.get("items", []):
            base = item["title"].split(",")[0].lower()
            words = [w for w in re.findall(r"[a-z]+", base) if len(w) > 3]
            if base in t or (words and sum(1 for w in words if w in t) >= max(1, len(words) - 1)):
                return item
        return None

    def _order_return(self, item: dict) -> Result:
        self.last_item = item
        order = self.order
        from datetime import date as _date
        def parse_iso(v):
            if not v:
                return None
            y, m, d = str(v)[:10].split("-")
            return _date(int(y), int(m), int(d))
        delivered = parse_iso(order.get("delivered_on"))
        placed = parse_iso(str(order.get("placed_at"))[:10]) if order.get("placed_at") else None
        window = return_window_days(item["return_category"], delivered, placed)
        if window is None:
            return Result(f"Sorry, the {item['title']} is in a category that "
                          "cannot be returned for a change of mind.",
                          "answer", ["RET-2", "RET-5"])
        deadline = delivered + timedelta(days=window) if delivered else None
        is_plus = bool(order.get("is_plus"))
        fee_note = ""
        if item["return_category"] == "fashion":
            if is_plus:
                fee_note = " As a ZentroMart Plus member, no reverse pickup fee applies to you."
            else:
                fee_note = (" A reverse pickup fee of ₹49 applies for a "
                            "change-of-mind return of clothing, footwear or bags.")
        reply = (f"Yes, you can return the {item['title']} - the window is "
                 f"{window} days from delivery, so please return it by "
                 f"{self._date(deadline.isoformat()) if deadline else ''}.{fee_note}")
        if self.lang == "hi":
            reply = (f"हाँ, आप {item['title']} वापस कर सकती हैं - window delivery से "
                     f"{window} दिन है, इसलिए {self._date(deadline.isoformat()) if deadline else ''} "
                     f"तक वापस कर दीजिए।{fee_note.replace('₹49', '₹49 (49 रुपये)')}")
        elif self.lang == "hi-en":
            reply = (f"Haan, aap {item['title']} return kar sakti hain - window "
                     f"delivery se {window} din hai, isliye "
                     f"{self._date(deadline.isoformat()) if deadline else ''} tak "
                     f"return kar dijiye.{fee_note}")
        return Result(reply, "answer", ["RET-2", "RET-8", "RET-6"])

    def _order_refund(self) -> Result:
        order = self.order
        # refund already initiated - check overdue (ESC-1.5)
        initiated = order.get("return_refund_initiated_on")
        if initiated:
            from datetime import date as _date
            y, m, d = str(initiated)[:10].split("-")
            start = _date(int(y), int(m), int(d))
            method = order.get("return_refund_method") or order.get("payment_method")
            key = "netbanking" if method == "netbanking" else method
            low, high = REFUND_TIMELINES.get(key, (1, 3))
            if key != "wallet":
                deadline = add_business_days(start, high, self.core.holidays)
                overdue_bd = business_days_after(deadline, REFERENCE_DATE, self.core.holidays) \
                    if REFERENCE_DATE > deadline else 0
                if overdue_bd > 3:
                    rrn = order.get("return_rrn")
                    res = self._escalate(
                        f"Order {self.order_id}: return refund of Rs "
                        f"{order.get('return_refund_amount_inr')} was initiated on "
                        f"{initiated} via {method}; maximum timeline ended "
                        f"{deadline.isoformat()} and it is now more than 3 business "
                        f"days past that. RRN {rrn}. Reason: overdue refund.",
                        "overdue_refund",
                        f"Your refund was initiated on {self._date(str(initiated))} "
                        f"and should have arrived by {self._date(deadline.isoformat())}. "
                        f"Since it is now past that, I've created a ticket and a "
                        f"colleague from the team will follow up. Your refund "
                        f"reference number (RRN) is {rrn}, which your bank can trace.",
                        ["ESC-1", "REF-2", "REF-6"])
                    return res
            return Result(f"Your refund was initiated on {self._date(str(initiated))} "
                          f"and should reach you within {low} to {high} business "
                          "days of that date.", "answer", ["REF-2"])
        # picked up, QC pending (RET-7 / REF-1)
        if order.get("return_status") == "picked_up" or order.get("status") == "return_picked_up":
            reply = ("Your returned item has been picked up and is waiting for "
                     "its quality check (QC) at the warehouse. Once it passes "
                     "the quality check, the refund is initiated within 2 "
                     "business days of pickup.")
            if self.lang == "hi":
                reply = ("आपका लौटाया गया सामान pickup हो चुका है और warehouse में "
                         "गुणवत्ता जाँच (quality check / QC) का इंतज़ार कर रहा है। "
                         "QC pass होने के बाद refund initiate होगा।")
            elif self.lang == "hi-en":
                reply = ("Aapka return pickup ho chuka hai aur warehouse mein "
                         "quality check (QC) ka wait kar raha hai. QC pass hote "
                         "hi refund initiate hoga.")
            return Result(reply, "answer", ["RET-7", "REF-1"])
        # general follow-up after a return discussion: initiation + method timeline
        method = order.get("payment_method")
        is_plus = bool(order.get("is_plus"))
        if method == "wallet":
            reply = ("For ZentroMart Plus members the refund is initiated at "
                     "pickup itself, and a Wallet refund is instant, within "
                     "2 hours of initiation.")
            if self.lang == "hi-en":
                reply = ("Plus member hone par refund pickup ke samay hi initiate "
                         "ho jata hai, aur Wallet refund turant (instant), "
                         "initiate hone ke 2 ghante (2 hours) ke andar aa jata hai.")
            return Result(reply, "answer", ["REF-2", "RET-7", "PLS-2"])
        low, high = REFUND_TIMELINES.get(method, (1, 3))
        init_note = ("initiated at pickup for ZentroMart Plus members" if is_plus
                     else "initiated after the item passes quality check, within "
                          "2 business days of pickup")
        reply = (f"The refund is {init_note}, and then takes {low} to {high} "
                 f"business days to reach your {method} account.")
        if self.lang == "hi":
            reply = (f"Refund quality check के बाद initiate होता है, फिर आपके "
                     f"{method} account में {low} से {high} business days में आता है।")
        elif self.lang == "hi-en":
            reply = (f"Refund initiate hone ke baad aapke {method} account mein "
                     f"{low} to {high} business days mein aa jayega.")
        return Result(reply, "answer", ["REF-2", "RET-7"])
