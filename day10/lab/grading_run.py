#!/usr/bin/env python3
"""
Chạy bộ câu grading (retrieval + keyword) — output JSONL cho giảng viên.

  python grading_run.py --out artifacts/eval/grading_run.jsonl

Yêu cầu: đã chạy `python etl_pipeline.py run` trước để có collection Chroma.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
ROOT = Path(__file__).resolve().parent


def _load_questions(path: Path) -> list[dict]:
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


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--questions",
        default=str(ROOT / "data" / "grading_questions.json"),
    )
    p.add_argument(
        "--out",
        default=str(ROOT / "artifacts" / "eval" / "grading_run.jsonl"),
    )
    p.add_argument("--top-k", type=int, default=5)
    args = p.parse_args()

    try:
        import chromadb
        from chromadb.utils import embedding_functions
    except ImportError:
        print("pip install chromadb sentence-transformers", file=sys.stderr)
        return 1

    qpath = Path(args.questions)
    try:
        qs = _load_questions(qpath)
    except ValueError as exc:
        print(f"Questions error: {exc}", file=sys.stderr)
        return 2

    db_path = os.environ.get("CHROMA_DB_PATH", str(ROOT / "chroma_db"))
    collection_name = os.environ.get("CHROMA_COLLECTION", "day10_kb")
    model_name = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

    try:
        client = chromadb.PersistentClient(path=db_path)
        emb = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=model_name)
        col = client.get_collection(name=collection_name, embedding_function=emb)
    except Exception as exc:
        print(f"Vector store setup error: {exc}", file=sys.stderr)
        return 3

    out = Path(args.out)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            for q in qs:
                text = q["question"]
                try:
                    res = col.query(query_texts=[text], n_results=args.top_k)
                except Exception as exc:
                    print(
                        f"Query error for {q.get('id', '<unknown>')}: {exc}",
                        file=sys.stderr,
                    )
                    return 4
                docs = (res.get("documents") or [[]])[0]
                metas = (res.get("metadatas") or [[]])[0]
                blob = " ".join(docs).lower()
                must_any = [x.lower() for x in q.get("must_contain_any", [])]
                forbidden = [x.lower() for x in q.get("must_not_contain", [])]
                ok_any = any(m in blob for m in must_any) if must_any else True
                bad_forb = any(m in blob for m in forbidden) if forbidden else False
                top_doc = (metas[0] or {}).get("doc_id", "") if metas else ""
                want_top1 = (q.get("expect_top1_doc_id") or "").strip()
                top1_ok = True
                if want_top1:
                    top1_ok = top_doc == want_top1
                rec = {
                    "id": q.get("id"),
                    "question": text,
                    "top1_doc_id": top_doc,
                    "contains_expected": ok_any,
                    "hits_forbidden": bad_forb,
                    "top1_doc_matches": top1_ok if want_top1 else None,
                    "top_k_used": args.top_k,
                    "grading_criteria": q.get("grading_criteria", []),
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"Output error: {exc}", file=sys.stderr)
        return 5
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
