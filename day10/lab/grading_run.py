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
from evaluation_utils import load_questions, positive_int, score_retrieval

load_dotenv()
ROOT = Path(__file__).resolve().parent


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
    p.add_argument("--top-k", type=positive_int, default=5)
    args = p.parse_args()

    try:
        import chromadb
        from chromadb.utils import embedding_functions
    except ImportError:
        print("pip install chromadb sentence-transformers", file=sys.stderr)
        return 1

    qpath = Path(args.questions)
    try:
        qs = load_questions(qpath)
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
    tmp_path = out.with_name(f".{out.name}.{os.getpid()}.tmp")
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        with tmp_path.open("w", encoding="utf-8") as f:
            for q in qs:
                text = q["question"]
                try:
                    res = col.query(query_texts=[text], n_results=args.top_k)
                except Exception as exc:
                    tmp_path.unlink(missing_ok=True)
                    print(
                        f"Query error for {q.get('id', '<unknown>')}: {exc}",
                        file=sys.stderr,
                    )
                    return 4
                docs = (res.get("documents") or [[]])[0]
                metas = (res.get("metadatas") or [[]])[0]
                score = score_retrieval(q, docs, metas)
                rec = {
                    "id": q.get("id"),
                    "question": text,
                    "top1_doc_id": score["top_doc"],
                    "contains_expected": score["contains_expected"],
                    "hits_forbidden": score["hits_forbidden"],
                    "top1_doc_matches": score["top1_matches"],
                    "top_k_used": args.top_k,
                    "grading_criteria": q.get("grading_criteria", []),
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        tmp_path.replace(out)
    except OSError as exc:
        tmp_path.unlink(missing_ok=True)
        print(f"Output error: {exc}", file=sys.stderr)
        return 5
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
