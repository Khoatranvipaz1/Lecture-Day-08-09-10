#!/usr/bin/env python3
"""
Đánh giá retrieval đơn giản — before/after khi pipeline đổi dữ liệu embed.

Không bắt buộc LLM: chỉ kiểm tra top-k chunk có chứa keyword kỳ vọng hay không
(tiếp nối tinh thần Day 08/09 nhưng tập trung data layer).
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from evaluation_utils import load_questions, positive_int, score_retrieval

load_dotenv()

ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--questions",
        default=str(ROOT / "data" / "test_questions.json"),
        help="JSON danh sách câu hỏi golden (retrieval)",
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "artifacts" / "eval" / "before_after_eval.csv"),
        help="CSV kết quả",
    )
    parser.add_argument("--top-k", type=positive_int, default=3)
    args = parser.parse_args()

    try:
        import chromadb
        from chromadb.utils import embedding_functions
    except ImportError:
        print("Install: pip install chromadb sentence-transformers", file=sys.stderr)
        return 1

    qpath = Path(args.questions)
    if not qpath.is_file():
        print(f"questions not found: {qpath}", file=sys.stderr)
        return 1

    try:
        questions = load_questions(qpath)
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
    except Exception as e:
        print(f"Vector store setup error: {e}", file=sys.stderr)
        return 3

    out_path = Path(args.out)
    tmp_path = out_path.with_name(f".{out_path.name}.{os.getpid()}.tmp")
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "question_id",
            "question",
            "top1_doc_id",
            "top1_preview",
            "contains_expected",
            "hits_forbidden",
            "top1_doc_expected",
            "top_k_used",
        ]
        with tmp_path.open("w", encoding="utf-8", newline="") as fcsv:
            w = csv.DictWriter(fcsv, fieldnames=fieldnames)
            w.writeheader()
            for q in questions:
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
                preview = (docs[0] or "")[:180].replace("\n", " ") if docs else ""
                top1_expected = ""
                if score["expected_doc"]:
                    top1_expected = "yes" if score["top1_matches"] else "no"
                w.writerow(
                    {
                        "question_id": q.get("id", ""),
                        "question": text,
                        "top1_doc_id": score["top_doc"],
                        "top1_preview": preview,
                        "contains_expected": "yes" if score["contains_expected"] else "no",
                        "hits_forbidden": "yes" if score["hits_forbidden"] else "no",
                        "top1_doc_expected": top1_expected,
                        "top_k_used": args.top_k,
                    }
                )
        tmp_path.replace(out_path)
    except OSError as exc:
        tmp_path.unlink(missing_ok=True)
        print(f"Output error: {exc}", file=sys.stderr)
        return 5

    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
