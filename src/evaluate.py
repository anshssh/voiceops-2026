"""Evaluation against the practice sets - the dataset's own scoring rules.

must_include: groups split by ' ; ', each group passes if ANY alternative
(split by ' / ') appears in the reply (case-insensitive). Dates/numbers
accept equivalent forms because replies include the English date form.
must_not_include: any listed phrase in the reply fails that check.
Retrieval: gold_evidence section IDs vs the agent's reported evidence.
"""
from __future__ import annotations

import csv
import os


def check_must_include(reply: str, spec: str) -> tuple[bool, list[str]]:
    if not spec:
        return True, []
    low = reply.lower()
    missing = []
    for group in spec.split(" ; "):
        group = group.strip()
        if not group:
            continue
        alts = [a.strip().lower() for a in group.split(" / ")]
        if not any(a in low for a in alts):
            missing.append(group)
    return not missing, missing


def check_must_not(reply: str, spec: str) -> tuple[bool, list[str]]:
    if not spec:
        return True, []
    low = reply.lower()
    bad = [p.strip() for p in spec.split(" ; ")
           if p.strip() and p.strip().lower() in low]
    return not bad, bad


def parse_gold(spec: str) -> list[str]:
    return [s.strip() for s in spec.split(" ; ") if s.strip()] if spec else []


def evaluate_questions(agent_answer_fn, questions_csv: str) -> dict:
    rows = list(csv.DictReader(open(questions_csv, encoding="utf-8")))
    passed = decision_ok = retrieval_hit = 0
    failures = []
    for row in rows:
        res = agent_answer_fn(row["question"])
        reply = res.reply if hasattr(res, "reply") else res["reply"]
        decision = res.decision if hasattr(res, "decision") else res["decision"]
        evidence = res.evidence if hasattr(res, "evidence") else res["evidence"]
        inc_ok, missing = check_must_include(reply, row["must_include"])
        not_ok, bad = check_must_not(reply, row["must_not_include"])
        acceptable = [d.strip() for d in row["acceptable_decisions"].split(";") if d.strip()] \
            or [row["expected_decision"]]
        dec_ok = decision in acceptable
        gold = parse_gold(row["gold_evidence"])
        hit = bool(set(gold) & set(evidence)) if gold else None
        ok = inc_ok and not_ok and dec_ok
        passed += ok
        decision_ok += dec_ok
        if hit:
            retrieval_hit += 1
        if not ok:
            failures.append({"id": row["id"], "question": row["question"],
                             "missing": missing, "forbidden": bad,
                             "decision": decision, "expected": acceptable,
                             "reply": reply, "evidence": evidence, "gold": gold})
    n = len(rows)
    answerable_gold = sum(1 for r in rows if parse_gold(r["gold_evidence"]))
    return {"total": n, "passed": passed, "accuracy": round(passed / n, 3),
            "decision_accuracy": round(decision_ok / n, 3),
            "retrieval_hit_rate": round(retrieval_hit / answerable_gold, 3) if answerable_gold else None,
            "failures": failures}


def evaluate_conversations(make_agent, conversations_csv: str) -> dict:
    rows = list(csv.DictReader(open(conversations_csv, encoding="utf-8")))
    convs: dict[str, list[dict]] = {}
    for row in rows:
        convs.setdefault(row["conversation_id"], []).append(row)
    total = passed = decision_ok = 0
    failures = []
    for cid, turns in convs.items():
        agent = make_agent()
        for row in sorted(turns, key=lambda r: int(r["turn"])):
            res = agent.respond(row["customer_message"])
            total += 1
            inc_ok, missing = check_must_include(res.reply, row["must_include"])
            not_ok, bad = check_must_not(res.reply, row["must_not_include"])
            dec_ok = res.decision == row["expected_decision"]
            ok = inc_ok and not_ok and dec_ok
            passed += ok
            decision_ok += dec_ok
            if not ok:
                failures.append({"conversation": cid, "turn": row["turn"],
                                 "message": row["customer_message"],
                                 "missing": missing, "forbidden": bad,
                                 "decision": res.decision,
                                 "expected": row["expected_decision"],
                                 "reply": res.reply, "evidence": res.evidence,
                                 "gold": parse_gold(row["gold_evidence"])})
    return {"total_turns": total, "passed": passed,
            "accuracy": round(passed / total, 3),
            "decision_accuracy": round(decision_ok / total, 3),
            "failures": failures}
