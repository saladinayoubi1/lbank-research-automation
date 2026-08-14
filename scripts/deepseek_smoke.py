"""Tiny paid smoke probe for the bounded NEXUS DeepSeek provider."""

from __future__ import annotations

import json
import os

from deepseek_provider import DeepSeekError, chat

PAID_ROUTING_FLAG = "NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED"


def main() -> None:
    if os.environ.get(PAID_ROUTING_FLAG) != "1":
        raise DeepSeekError("DeepSeek paid routing is not explicitly authorized")

    result = chat(
        [
            {
                "role": "user",
                "content": "Reply with exactly: NEXUS_DEEPSEEK_OK",
            }
        ],
        complexity="routine",
        max_tokens=32,
        ledger_path="build/deepseek/usage.json",
        timeout=90,
    )
    ok = result["content"].strip() == "NEXUS_DEEPSEEK_OK"
    safe = {
        "ok": ok,
        "model": result["model"],
        "thinking": result["thinking"],
        "cost_usd": round(result["cost_usd"], 8),
        "month_spent_usd": result["month_spent_usd"],
        "month_remaining_usd": result["month_remaining_usd"],
    }
    print(json.dumps(safe, sort_keys=True))
    if not ok:
        raise SystemExit("DeepSeek smoke response mismatch")


if __name__ == "__main__":
    main()
