#!/usr/bin/env python3
"""Run Step 1 vs Step 2 on practice/questions.csv and Step 3 on conversations.

Usage: python scripts/run_evaluation.py --data-dir ../dataset
Writes evaluation_results.json next to this script's project root.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.agent import SupportAgent
from src.baseline import PromptOnlyBaseline
from src.conversation import ConversationAgent
from src.evaluate import evaluate_conversations, evaluate_questions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=os.environ.get(
        "VOICEOPS_DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "dataset")))
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(__file__), "..", "evaluation_results.json"))
    args = ap.parse_args()
    data = os.path.abspath(args.data_dir)

    baseline = PromptOnlyBaseline()
    step1 = evaluate_questions(baseline.answer, os.path.join(data, "practice", "questions.csv"))

    agent = SupportAgent(data)
    step2 = evaluate_questions(agent.answer, os.path.join(data, "practice", "questions.csv"))

    def make_conv():
        return ConversationAgent(SupportAgent(data))
    step3 = evaluate_conversations(make_conv, os.path.join(data, "practice", "conversations.csv"))

    results = {"step1_prompt_only": {k: v for k, v in step1.items() if k != "failures"},
               "step2_rag": {k: v for k, v in step2.items() if k != "failures"},
               "step3_conversations": {k: v for k, v in step3.items() if k != "failures"},
               "step1_failures": step1["failures"],
               "step2_failures": step2["failures"],
               "step3_failures": step3["failures"]}
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)
    print(json.dumps({k: results[k] for k in
                      ("step1_prompt_only", "step2_rag", "step3_conversations")}, indent=2))
    print(f"\nFull results (with failures) -> {args.out}")


if __name__ == "__main__":
    main()
