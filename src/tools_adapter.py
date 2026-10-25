"""Adapter around the dataset's mock tools (dataset/tools/tools.py).

We import the *provided* tools module unchanged - lookup_order enforces
caller verification itself, create_ticket writes tools/tickets_created.csv.
The dataset directory is located via VOICEOPS_DATA_DIR or --data-dir.
"""
from __future__ import annotations

import importlib.util
import os
import sys


class ToolLayer:
    def __init__(self, dataset_dir: str):
        self.dataset_dir = dataset_dir
        tools_dir = os.path.join(dataset_dir, "tools")
        if tools_dir not in sys.path:
            sys.path.insert(0, os.path.dirname(dataset_dir.rstrip("/")))
        # The provided tools package resolves data/ relative to itself,
        # so load it by file location to avoid name clashes.
        spec = importlib.util.spec_from_file_location(
            "voiceops_dataset_tools", os.path.join(tools_dir, "tools.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self._lookup = module.lookup_order
        self._create = module.create_ticket
        self.calls: list[dict] = []  # audit log for evaluation

    def lookup_order(self, order_id: str, verification_value: str | None = None) -> dict:
        result = self._lookup(order_id, verification_value=verification_value)
        self.calls.append({"tool": "lookup_order", "order_id": str(order_id),
                           "verification_value": verification_value,
                           "verified": result.get("verified", False)})
        return result

    def create_ticket(self, summary: str, order_id: str | None = None,
                      reason: str | None = None, intent: str | None = None) -> dict:
        result = self._create(summary, order_id=order_id, reason=reason, intent=intent)
        self.calls.append({"tool": "create_ticket", "order_id": order_id,
                           "reason": reason, "created": result.get("created", False)})
        return result
