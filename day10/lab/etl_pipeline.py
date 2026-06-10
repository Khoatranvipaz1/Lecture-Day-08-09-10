#!/usr/bin/env python3
"""
Lab Day 10 — ETL entrypoint: ingest → clean → validate → embed.

Tiếp nối Day 09: cùng corpus docs trong data/docs/; pipeline này xử lý *export* raw (CSV)
đại diện cho lớp ingestion từ DB/API trước khi embed lại vector store.

Chạy nhanh:
  pip install -r requirements.txt
  cp .env.example .env
  python etl_pipeline.py run

Chế độ inject (Sprint 3 — bỏ fix refund để expectation fail / eval xấu):
  python etl_pipeline.py run --no-refund-fix --skip-validate
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from monitoring.freshness_check import check_manifest_freshness
from quality.expectations import run_expectations
from transform.cleaning_rules import clean_rows, load_raw_csv, write_cleaned_csv, write_quarantine_csv

load_dotenv()

ROOT = Path(__file__).resolve().parent
RAW_DEFAULT = ROOT / "data" / "raw" / "policy_export_dirty.csv"
ART = ROOT / "artifacts"
LOG_DIR = ART / "logs"
MAN_DIR = ART / "manifests"
QUAR_DIR = ART / "quarantine"
CLEAN_DIR = ART / "cleaned"


def _log(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def cmd_run(args: argparse.Namespace) -> int:
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%MZ")
    raw_path = Path(args.raw)
    if not raw_path.is_file():
        print(f"ERROR: raw file not found: {raw_path}", file=sys.stderr)
        return 1

    log_path = LOG_DIR / f"run_{run_id.replace(':', '-')}.log"
    for p in (LOG_DIR, MAN_DIR, QUAR_DIR, CLEAN_DIR):
        p.mkdir(parents=True, exist_ok=True)
    # A run_id identifies one evidence snapshot; rerunning it replaces its log.
    log_path.write_text("", encoding="utf-8")

    def log(msg: str) -> None:
        print(msg)
        _log(log_path, msg)

    rows = load_raw_csv(raw_path)
    raw_count = len(rows)
    log(f"run_id={run_id}")
    log(f"raw_records={raw_count}")

    cleaned, quarantine = clean_rows(
        rows,
        apply_refund_window_fix=not args.no_refund_fix,
    )
    cleaned_path = CLEAN_DIR / f"cleaned_{run_id.replace(':', '-')}.csv"
    quar_path = QUAR_DIR / f"quarantine_{run_id.replace(':', '-')}.csv"
    write_cleaned_csv(cleaned_path, cleaned)
    write_quarantine_csv(quar_path, quarantine)

    log(f"cleaned_records={len(cleaned)}")
    log(f"quarantine_records={len(quarantine)}")
    log(f"cleaned_csv={cleaned_path.relative_to(ROOT)}")
    log(f"quarantine_csv={quar_path.relative_to(ROOT)}")

    results, halt = run_expectations(cleaned)
    for r in results:
        sym = "OK" if r.passed else "FAIL"
        log(f"expectation[{r.name}] {sym} ({r.severity}) :: {r.detail}")
    if halt and not args.skip_validate:
        log("PIPELINE_HALT: expectation suite failed (halt).")
        return 2
    if halt and args.skip_validate:
        log("WARN: expectation failed but --skip-validate -> continuing demo embed.")

    # Embed
    embed_ok = cmd_embed_internal(
        cleaned_path,
        run_id=run_id,
        log=log,
    )
    if not embed_ok:
        return 3

    latest_exported = ""
    source_watermarks: dict[str, str] = {}
    if cleaned:
        latest_exported = max((r.get("exported_at") or "" for r in cleaned), default="")
        for row in cleaned:
            doc_id = str(row.get("doc_id") or "")
            exported_at = str(row.get("exported_at") or "")
            source_watermarks[doc_id] = max(source_watermarks.get(doc_id, ""), exported_at)
    oldest_source_exported = min(source_watermarks.values(), default="")

    manifest = {
        "run_id": run_id,
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "raw_path": str(raw_path.relative_to(ROOT)),
        "raw_records": raw_count,
        "cleaned_records": len(cleaned),
        "quarantine_records": len(quarantine),
        "published_vectors": len(cleaned),
        "publish_strategy": "upsert_verify_prune",
        "latest_exported_at": latest_exported,
        "oldest_source_exported_at": oldest_source_exported,
        "source_watermarks": source_watermarks,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "no_refund_fix": bool(args.no_refund_fix),
        "skipped_validate": bool(args.skip_validate and halt),
        "cleaned_csv": str(cleaned_path.relative_to(ROOT)),
        "chroma_path": os.environ.get("CHROMA_DB_PATH", "./chroma_db"),
        "chroma_collection": os.environ.get("CHROMA_COLLECTION", "day10_kb"),
    }
    man_path = MAN_DIR / f"manifest_{run_id.replace(':', '-')}.json"
    man_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"manifest_written={man_path.relative_to(ROOT)}")

    status, fdetail = check_manifest_freshness(
        man_path,
        sla_hours=float(os.environ.get("FRESHNESS_SLA_HOURS", "24")),
    )
    log(f"freshness_check={status} {json.dumps(fdetail, ensure_ascii=False)}")

    log("PIPELINE_OK")
    return 0


def cmd_embed_internal(cleaned_csv: Path, *, run_id: str, log) -> bool:
    try:
        import chromadb
        from chromadb.utils import embedding_functions
    except ImportError:
        log("ERROR: chromadb chưa cài. pip install -r requirements.txt")
        return False

    db_path = os.environ.get("CHROMA_DB_PATH", str(ROOT / "chroma_db"))
    collection_name = os.environ.get("CHROMA_COLLECTION", "day10_kb")
    model_name = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

    from transform.cleaning_rules import load_raw_csv as load_csv  # same loader

    try:
        rows = load_csv(cleaned_csv)
    except (OSError, csv.Error) as exc:
        log(f"ERROR: cannot read cleaned CSV: {exc}")
        return False
    if not rows:
        log("WARN: cleaned CSV rỗng — không embed.")
        return True

    try:
        client = chromadb.PersistentClient(path=db_path)
        emb = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=model_name)
        col = client.get_or_create_collection(name=collection_name, embedding_function=emb)
    except Exception as exc:
        log(f"ERROR: vector store setup failed: {exc}")
        return False

    ids = [r["chunk_id"] for r in rows]
    target_ids = set(ids)
    previous_ids: set[str] = set()
    try:
        prev = col.get(include=[])
        previous_ids = set(prev.get("ids") or [])
    except Exception as e:
        log(f"WARN: cannot inspect previous snapshot: {e}")
    documents = [r["chunk_text"] for r in rows]
    metadatas = [
        {
            "doc_id": r.get("doc_id", ""),
            "effective_date": r.get("effective_date", ""),
            "run_id": run_id,
        }
        for r in rows
    ]
    # Publish new/changed rows first so an upsert failure cannot remove serving data.
    try:
        col.upsert(ids=ids, documents=documents, metadatas=metadatas)
    except Exception as exc:
        log(f"ERROR: embed upsert failed: {exc}")
        return False
    log(f"embed_upsert count={len(ids)} collection={collection_name}")

    try:
        published = col.get(ids=ids, include=[])
        published_ids = set(published.get("ids") or [])
    except Exception as exc:
        log(f"ERROR: embed verification failed: {exc}")
        return False
    missing_ids = sorted(target_ids - published_ids)
    if missing_ids:
        log(f"ERROR: embed verification missing_ids={len(missing_ids)}")
        return False
    log(f"embed_verify count={len(published_ids)}")

    # Prune only after the target snapshot has been verified.
    drop = sorted(previous_ids - target_ids)
    if drop:
        try:
            col.delete(ids=drop)
        except Exception as exc:
            log(f"ERROR: embed prune failed: {exc}")
            return False
    log(f"embed_prune_removed={len(drop)}")

    try:
        final = col.get(include=[])
        final_ids = set(final.get("ids") or [])
    except Exception as exc:
        log(f"ERROR: final snapshot verification failed: {exc}")
        return False
    if final_ids != target_ids:
        log(
            "ERROR: final snapshot mismatch "
            f"expected={len(target_ids)} actual={len(final_ids)}"
        )
        return False
    log(f"embed_snapshot_count={len(final_ids)}")
    return True


def cmd_freshness(args: argparse.Namespace) -> int:
    p = Path(args.manifest)
    if not p.is_file():
        print(f"manifest not found: {p}", file=sys.stderr)
        return 1
    sla = float(os.environ.get("FRESHNESS_SLA_HOURS", "24"))
    status, detail = check_manifest_freshness(p, sla_hours=sla)
    print(status, json.dumps(detail, ensure_ascii=False))
    return 0 if status != "FAIL" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Day 10 ETL pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="ingest → clean → validate → embed")
    p_run.add_argument("--raw", default=str(RAW_DEFAULT), help="Đường dẫn CSV raw export")
    p_run.add_argument("--run-id", default="", help="ID run (mặc định: UTC timestamp)")
    p_run.add_argument(
        "--no-refund-fix",
        action="store_true",
        help="Không áp dụng rule fix cửa sổ 14→7 ngày (dùng cho inject corruption / before).",
    )
    p_run.add_argument(
        "--skip-validate",
        action="store_true",
        help="Vẫn embed khi expectation halt (chỉ phục vụ demo có chủ đích).",
    )
    p_run.set_defaults(func=cmd_run)

    p_fr = sub.add_parser("freshness", help="Đọc manifest và kiểm tra SLA freshness")
    p_fr.add_argument("--manifest", required=True)
    p_fr.set_defaults(func=cmd_freshness)

    args = parser.parse_args()
    try:
        return int(args.func(args))
    except (OSError, csv.Error, json.JSONDecodeError, ValueError) as exc:
        print(f"PIPELINE_ERROR: {exc}", file=sys.stderr)
        return 10
    except Exception as exc:
        print(f"PIPELINE_UNEXPECTED_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 11


if __name__ == "__main__":
    raise SystemExit(main())
