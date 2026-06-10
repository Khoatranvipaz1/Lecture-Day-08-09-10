"""Shared loading and scoring helpers for retrieval eval entrypoints."""

from __future__ import annotations

import json
import argparse
from pathlib import Path
from typing import Any


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return parsed


def load_questions(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ValueError(f"questions not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read questions file: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid questions JSON: {exc}") from exc
    if not isinstance(data, list) or not data:
        raise ValueError("questions JSON must be a non-empty list")
    for index, question in enumerate(data, 1):
        if not isinstance(question, dict) or not str(question.get("question") or "").strip():
            raise ValueError(f"question #{index} is missing a non-empty 'question'")
    return data


def score_retrieval(
    question: dict[str, Any],
    documents: list[str],
    metadatas: list[dict[str, Any] | None],
) -> dict[str, Any]:
    blob = " ".join(documents).lower()
    must_any = [str(value).lower() for value in question.get("must_contain_any", [])]
    forbidden = [str(value).lower() for value in question.get("must_not_contain", [])]
    top_doc = (metadatas[0] or {}).get("doc_id", "") if metadatas else ""
    expected_doc = str(question.get("expect_top1_doc_id") or "").strip()
    return {
        "top_doc": top_doc,
        "contains_expected": any(value in blob for value in must_any) if must_any else True,
        "hits_forbidden": any(value in blob for value in forbidden) if forbidden else False,
        "expected_doc": expected_doc,
        "top1_matches": top_doc == expected_doc if expected_doc else None,
    }
