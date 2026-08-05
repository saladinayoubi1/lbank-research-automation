#!/usr/bin/env python3
"""Fail-closed structural validation for the NEXUS Zotero BibTeX bridge."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ENTRY_RE = re.compile(r"@([A-Za-z]+)\s*\{\s*([^,\s]+)\s*,", re.MULTILINE)
FIELD_RE = re.compile(r"\b(title|author|editor|year|date|doi|url)\s*=", re.IGNORECASE)


def validate(text: str) -> list[str]:
    errors: list[str] = []
    entries = ENTRY_RE.findall(text)
    keys = [key for _, key in entries]
    if len(keys) != len(set(keys)):
        errors.append("duplicate citation key")

    if text.count("{") != text.count("}"):
        errors.append("unbalanced braces")

    for match in ENTRY_RE.finditer(text):
        start = match.start()
        next_match = ENTRY_RE.search(text, match.end())
        end = next_match.start() if next_match else len(text)
        block = text[start:end]
        if not FIELD_RE.search(block):
            errors.append(f"entry {match.group(2)} has no identifying metadata")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bibtex", type=Path)
    args = parser.parse_args()
    try:
        text = args.bibtex.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"invalid BibTeX: {exc}", file=sys.stderr)
        return 1

    errors = validate(text)
    if errors:
        for error in errors:
            print(f"invalid BibTeX: {error}", file=sys.stderr)
        return 1

    print(f"valid BibTeX: {len(ENTRY_RE.findall(text))} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
