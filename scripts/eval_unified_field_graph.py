#!/usr/bin/env python3
"""Unified per-field extract eval harness on the LangGraph extract layer.

Same CLI, run-dir layout, checkpoint/resume, temporal disk cache, scoring and
summary/details JSON as the frozen 2026-11-13 harness
(tests/evaluation/extract/fixtures/legacy_harness_snapshot_20261113.py.txt), but each
(event, field) is extracted by ``src.evaluation.extract.graph.run_field``:

  Pass A: RULES-only if rules exist
  Pass B: GLiNER + TEMPORAL if A null / no rules
  Pass C: optional validate (pack.validate_fields)

Pack-specific harness settings (default --gt/--out, GT row -> preprocess event id,
party-name scoring fields) live in ``HARNESS_CONFIGS`` here, never in
``src/evaluation/extract``. A pack without an entry runs only with explicit --gt and
--out, and resolves event ids from the GT row's ``event_id`` column. Contexts are keyed per GT row (``<accession>#<row>``)
because merger GT repeats accessions with different passages; outputs report the
real accession.

Prefer ``--backend orin`` + ``gemma4:26b`` on the AGX Orin hub (``OLLAMA_HOST``).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, NamedTuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.action_packs import get_pack
from src.evaluation.action_packs.base import ActionPack
from src.evaluation.experiments import ensure_holdout
from src.evaluation.extract.dtos import FieldExtractRequest, FieldExtractResult
from src.evaluation.extract.graph import build_extract_graph, run_field
from src.evaluation.extract.providers import ArtifactProvider, EventContext
from src.evaluation.extract.temporal import TemporalFor, precompute_temporal
from src.evaluation.llm_backends import load_dotenv, make_backend
from src.evaluation.tender import gt_event_ids_from_corpus, load_gt, normalize, soft_match
from src.preprocess.store import DEFAULT_PREPROCESS_ROOT, ArtifactStore

TEMPORAL_MODEL = "satyaalmasian/temporal_tagger_BERT_tokenclassifier"
# qwen/qwen3-4b:free retired on OpenRouter; use a free hosted model instead.
DEFAULT_MODEL = "google/gemma-4-26b-a4b-it:free"
_NA = frozenset({"", "n/a", "na", "none", "null", "-", "—", "unknown", "not specified"})
ORACLE_MICRO = 0.837
ALLSPANS_MICRO = 0.481
PROMPT_V2_MICRO = 0.468
# Keys of a field result in checkpoint/details JSON (legacy extract_field dict shape)
RESULT_KEYS = ("pred", "pass_used", "n_evidence_chars", "n_rules", "raw_llm")


def _gt_ok(val: str | None) -> bool:
    v = (val or "").strip()
    return bool(v) and v.lower() not in _NA


def _acc(row: dict) -> str:
    return (row.get("accession_number") or "").strip()


# --- per-pack harness config ---------------------------------------------------------

EventIdFor = Callable[[dict], str | None]
# (eval rows, --documents-parquet) -> GT row -> preprocess event id
EventIdStrategy = Callable[[list[dict], Path], EventIdFor]
# Org-name fields scored with the party-tolerant matcher (CORP vs Corporation, ...)
PARTY_FIELDS = frozenset({"acquirer", "target", "security_description"})


def generic_event_ids(rows: list[dict], documents_parquet: Path) -> EventIdFor:
    """Default for packs without a resolver: the GT row's ``event_id`` (None when blank)."""

    def event_id_for(row: dict) -> str | None:
        return (row.get("event_id") or "").strip() or None

    return event_id_for


def tender_event_ids(rows: list[dict], documents_parquet: Path) -> EventIdFor:
    """Corpus accession->event_id map, else the GT row's ``event_id``."""
    acc_to_eid = (
        gt_event_ids_from_corpus({_acc(r) for r in rows}, documents_parquet)
        if documents_parquet.exists()
        else {}
    )

    def event_id_for(row: dict) -> str | None:
        # Prefer corpus preprocess ids — GT row.event_id (tender_offer_*) often has no artifacts
        return acc_to_eid.get(_acc(row)) or (row.get("event_id") or "").strip() or None

    return event_id_for


def merger_event_ids(rows: list[dict], documents_parquet: Path) -> EventIdFor:
    """``merger_{accession}``, else the GT row's ``event_id``."""

    def event_id_for(row: dict) -> str | None:
        acc = _acc(row)
        return f"merger_{acc}" if acc else (row.get("event_id") or "").strip() or None

    return event_id_for


class HarnessConfig(NamedTuple):
    """Harness-side settings for one pack; paths are relative to ``ROOT``.

    (NamedTuple, not a dataclass: tests load this script via importlib without
    registering it in ``sys.modules``, which ``@dataclass`` requires.)
    """

    gt: str
    out: str
    event_ids: EventIdStrategy = generic_event_ids
    party_fields: frozenset[str] = frozenset()


HARNESS_CONFIGS: dict[str, HarnessConfig] = {
    "tender": HarnessConfig(
        gt="notebooks/evaluation/tender_offers.csv",
        out="outputs/tender_eval",
        event_ids=tender_event_ids,
        party_fields=PARTY_FIELDS,
    ),
    "merger": HarnessConfig(
        gt="notebooks/evaluation/data/merger_2026-01-01_2026-09-30/mergers.csv",
        out="outputs/merger_eval",
        event_ids=merger_event_ids,
        party_fields=PARTY_FIELDS,
    ),
}


# --- temporal NER with the shared on-disk cache --------------------------------------


class DiskTemporalCache:
    """``temporal_for`` over ``<out>/temporal_cache/<pack>/<event_key>.json``.

    Shared across run-names so pause/fix/resume never re-NER the same filings. On a
    miss the tagger is loaded lazily (``tagger_loader``); with no tagger (``--no-temporal``)
    a miss returns {} and writes nothing, so it cannot poison later temporal runs.
    """

    def __init__(
        self, pack: ActionPack, cache_dir: Path, tagger_loader: Callable[[], Any]
    ) -> None:
        self.pack = pack
        self.cache_dir = cache_dir
        self.tagger_loader = tagger_loader
        self.hits = 0
        self.misses = 0

    def __call__(self, key: str, excerpts: str, fields: tuple[str, ...]) -> dict[str, list[str]]:
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            self.hits += 1
            return json.loads(path.read_text(encoding="utf-8"))
        self.misses += 1
        tagger = self.tagger_loader()
        if tagger is None:
            return {}
        cache = precompute_temporal(self.pack, tagger, excerpts, fields)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache), encoding="utf-8")
        return cache


# --- scoring -------------------------------------------------------------------------


def _prf(tp: int, fp: int, fn: int) -> dict[str, float | None]:
    p = tp / (tp + fp) if (tp + fp) else None
    r = tp / (tp + fn) if (tp + fn) else None
    f1 = (2 * p * r / (p + r)) if (p is not None and r is not None and (p + r)) else None
    return {"precision": p, "recall": r, "f1": f1}


def _party_soft_match(pred: str | None, gold: str | None) -> bool:
    """Org match tolerant of CORP/DE vs Corporation, Inc vs Incorporated."""
    if soft_match(pred, gold):
        return True
    p, g = normalize(pred), normalize(gold)
    if not p or not g:
        return False
    p = re.sub(r"/[a-z0-9]+$", "", p)
    g = re.sub(r"/[a-z0-9]+$", "", g)
    for long, short in (
        ("corporation", "corp"),
        ("incorporated", "inc"),
        ("company", "co"),
        ("limited", "ltd"),
    ):
        p, g = p.replace(long, short), g.replace(long, short)
    p, g = " ".join(p.split()), " ".join(g.split())
    return bool(p and g and (p == g or p in g or g in p))


def _score_one(
    stats: dict[str, Any],
    gold: str,
    pred: str | None,
    *,
    field: str = "",
    party_fields: frozenset[str] = PARTY_FIELDS,
) -> str:
    has_gt = _gt_ok(gold)
    has_pred = bool(normalize(pred))
    if has_gt:
        stats["gt_present"] += 1
    if has_pred:
        stats["pred_present"] += 1
    matched = (
        _party_soft_match(pred, gold)
        if field in party_fields
        else soft_match(pred, gold)
    )
    if has_gt and has_pred and matched:
        stats["tp"] += 1
        return "tp"
    if has_pred and not has_gt:
        stats["fp"] += 1
        return "fp_no_gt"
    if has_pred and has_gt:
        stats["fp"] += 1
        stats["fn"] += 1
        return "mismatch"
    if has_gt:
        stats["fn"] += 1
        return "fn"
    return "skip"


def _result_dict(result: FieldExtractResult) -> dict[str, Any]:
    dumped = result.model_dump()
    return {k: dumped[k] for k in RESULT_KEYS}


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser(
        description="Unified ActionPack cascade extract on the LangGraph extract layer"
    )
    p.add_argument("--gt", type=Path, default=None)
    p.add_argument("--out", type=Path, default=None)
    p.add_argument(
        "--pack",
        default="tender",
        help="ActionPack name (tender|merger; other packs need --gt and --out)",
    )
    p.add_argument(
        "--backend",
        default="orin",
        choices=("openrouter", "ollama", "free", "orin", "openai"),
    )
    p.add_argument("--model", default=None, help="Default: gemma4:26b for orin, else OpenRouter free")
    p.add_argument("--documents-parquet", type=Path, default=ROOT / "data/processed/documents.parquet")
    p.add_argument("--split", choices=("holdout", "train"), default="holdout")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--fields", default="core", help="'core' or comma-separated subset")
    p.add_argument("--run-name", default=None)
    p.add_argument("--device", default="cpu", help="temporal NER device (cpu recommended)")
    p.add_argument("--no-temporal", action="store_true")
    p.add_argument("--no-cascade", action="store_true", help="v1 one-shot mixed evidence")
    p.add_argument("--validate", action="store_true", default=True)
    p.add_argument("--no-validate", action="store_true")
    p.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Parallel LLM field-calls (1 = serial; Orin OLLAMA_NUM_PARALLEL=4 → use 4)",
    )
    args = p.parse_args(argv)

    try:
        pack = get_pack(args.pack)
    except KeyError as e:
        print(str(e), file=sys.stderr)
        return 2
    cfg = HARNESS_CONFIGS.get(pack.name)
    if cfg is None:
        if args.gt is None or args.out is None:
            print(
                f"pack={pack.name!r} has no harness config (known: "
                f"{', '.join(sorted(HARNESS_CONFIGS))}); pass both --gt and --out",
                file=sys.stderr,
            )
            return 2
        cfg = HarnessConfig(gt=str(args.gt), out=str(args.out))
    if args.gt is None:
        args.gt = ROOT / cfg.gt
    if args.out is None:
        args.out = ROOT / cfg.out
    if args.fields.strip().lower() == "core":
        fields: tuple[str, ...] = pack.fields
    else:
        fields = tuple(f.strip() for f in args.fields.split(",") if f.strip())
        bad = [f for f in fields if f not in pack.field_defs]
        if bad:
            print(f"unknown fields for pack={pack.name}: {bad}", file=sys.stderr)
            return 2

    cascade = not args.no_cascade
    validate = args.validate and not args.no_validate
    if not args.model:
        args.model = (
            "gemma4:26b"
            if args.backend in {"orin", "ollama", "openai"}
            else DEFAULT_MODEL
        )
    if args.backend in {"openrouter", "free"} and args.model in {"qwen3:4b", "qwen/qwen3-4b:free"}:
        args.model = DEFAULT_MODEL

    try:
        backend = make_backend(args.backend)
    except Exception as e:  # noqa: BLE001
        print(str(e), file=sys.stderr)
        return 3

    # ping
    try:
        backend.chat_json(
            system="Return JSON only.",
            user='Return {"ping": true}',
            model=args.model,
        )
    except Exception as e:  # noqa: BLE001
        print(f"LLM backend unreachable ({args.backend}/{args.model}): {e}", file=sys.stderr)
        return 3

    store = ArtifactStore(pack.name, DEFAULT_PREPROCESS_ROOT)
    _tagger_holder: dict[str, Any] = {"pipe": None}

    def _ensure_tagger():
        """Lazy-load BERT only on temporal cache miss."""
        if args.no_temporal:
            return None
        if _tagger_holder["pipe"] is None:
            from transformers import pipeline

            print(f"loading temporal tagger on {args.device}…", flush=True)
            _tagger_holder["pipe"] = pipeline(
                "token-classification",
                model=TEMPORAL_MODEL,
                aggregation_strategy="simple",
                device=args.device,
            )
        return _tagger_holder["pipe"]

    gt_rows = load_gt(args.gt)
    accessions = sorted({_acc(r) for r in gt_rows if r.get("accession_number")})
    holdout = set(ensure_holdout(args.out, accessions, n=20))
    if args.split == "holdout":
        rows = [r for r in gt_rows if _acc(r) in holdout]
    else:
        rows = [r for r in gt_rows if _acc(r) not in holdout]
    if args.limit:
        rows = rows[: args.limit]

    event_id_for = cfg.event_ids(rows, args.documents_parquet)

    model_tag = args.model.replace("/", "_").replace(":", "_").replace(".", "")
    run = args.run_name or (
        f"unified_field_{pack.name}_v2_{model_tag}_{args.split}"
        if cascade
        else f"unified_field_{pack.name}_oneshot_{model_tag}_{args.split}"
    )
    out_dir = args.out / "experiments" / "runs" / run
    out_dir.mkdir(parents=True, exist_ok=True)

    concurrency = max(1, int(args.concurrency))
    print(
        json.dumps(
            {
                "pack": pack.name,
                "backend": args.backend,
                "model": args.model,
                "cascade": cascade,
                "validate": validate,
                "concurrency": concurrency,
                "reasoning_effort": "none",
                "n_rows": len(rows),
                "n_fields": len(fields),
                "fields": list(fields),
                "run": run,
            },
            indent=2,
        ),
        flush=True,
    )

    stats = {f: {"tp": 0, "fp": 0, "fn": 0, "gt_present": 0, "pred_present": 0} for f in fields}
    pass_counts: dict[str, int] = {}
    from tqdm import tqdm

    ckpt_path = out_dir / "checkpoint.jsonl"
    # Shared across run-names so pause/fix/resume never re-NER the same filings
    temporal_dir = args.out / "temporal_cache" / pack.name
    temporal_dir.mkdir(parents=True, exist_ok=True)

    results_by_job: dict[tuple[int, str], dict[str, Any]] = {}
    if ckpt_path.exists():
        with ckpt_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                results_by_job[(int(rec["ei"]), str(rec["field"]))] = rec["result"]
        print(f"resume: loaded {len(results_by_job)} checkpointed field-calls", flush=True)

    # Per-row context keys: GT rows sharing an accession may carry different passages
    row_keys = {id(r): f"{_acc(r)}#{i}" for i, r in enumerate(rows)}
    temporal_for: TemporalFor = DiskTemporalCache(pack, temporal_dir, _ensure_tagger)
    provider = ArtifactProvider(
        pack,
        store,
        event_id_for=event_id_for,
        temporal_for=temporal_for,
        key_for=lambda r: row_keys[id(r)],
    )
    # Preload event artifacts once (temporal NER = disk cache only unless miss)
    print(f"temporal+load: preparing {len(rows)} rows…", file=sys.stderr, flush=True)
    keys = provider.prepare(rows, fields)
    print(
        f"temporal_cache hits={temporal_for.hits} misses={temporal_for.misses} "
        f"(tagger_loaded={_tagger_holder['pipe'] is not None})",
        flush=True,
    )

    def _request(ei: int, field: str, event_id: str | None) -> FieldExtractRequest:
        # accession carries the per-row context key; outputs use the row's real accession
        return FieldExtractRequest(
            pack_name=pack.name,
            field=field,
            event_id=event_id,
            accession=keys[ei],
            model=args.model,
            validate_enabled=validate,
            cascade=cascade,
        )

    # n_spans / n_excerpt_chars / event_id for details come from the prepared contexts
    contexts: list[EventContext] = [
        provider.context(_request(ei, "context", None)) for ei in range(len(rows))
    ]
    graph = build_extract_graph(pack, backend, provider)

    jobs: list[tuple[int, str]] = [
        (ei, field)
        for ei in range(len(rows))
        for field in fields
        if (ei, field) not in results_by_job
    ]
    total = len(rows) * len(fields)
    done = len(results_by_job)
    print(f"llm remaining={len(jobs)} done={done} total={total}", flush=True)

    def _run_job(ei: int, field: str) -> tuple[tuple[int, str], dict[str, Any]]:
        # run_field never raises: failures come back as pass_used="error"
        req = _request(ei, field, contexts[ei].event_id)
        return (ei, field), _result_dict(run_field(graph, req))

    t0 = time.perf_counter()
    if jobs:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futs = [pool.submit(_run_job, ei, field) for ei, field in jobs]
            pbar = tqdm(
                total=total,
                initial=done,
                desc="llm_fields",
                unit="call",
                file=sys.stderr,
            )
            try:
                with ckpt_path.open("a", encoding="utf-8") as ckpt_fh:
                    for fut in as_completed(futs):
                        key, result = fut.result()
                        results_by_job[key] = result
                        done += 1
                        ei, field = key
                        acc = _acc(rows[ei])
                        gold = (rows[ei].get(field) or "").strip()
                        line = (
                            f"[{done}/{total}] {acc} {field} pass={result['pass_used']} "
                            f"GT={gold!r} pred={result['pred']!r}"
                        )
                        print(line, flush=True)
                        tqdm.write(line, file=sys.stderr)
                        ckpt_fh.write(
                            json.dumps(
                                {
                                    "ei": ei,
                                    "field": field,
                                    "accession": acc,
                                    "result": result,
                                }
                            )
                            + "\n"
                        )
                        ckpt_fh.flush()
                        pbar.set_postfix_str(
                            f"{acc[-14:]} {field} {result['pass_used']}", refresh=False
                        )
                        pbar.update(1)
            finally:
                pbar.close()
    wall_s = time.perf_counter() - t0

    details: list[dict[str, Any]] = []
    for ei, row in enumerate(rows):
        ctx = contexts[ei]
        row_d: dict[str, Any] = {
            "accession": _acc(row),
            "event_id": ctx.event_id,
            "n_spans": len(ctx.spans),
            "n_excerpt_chars": len(ctx.excerpts),
            "fields": {},
        }
        for field in fields:
            result = results_by_job[(ei, field)]
            gold = (row.get(field) or "").strip()
            outcome = _score_one(
                stats[field], gold, result["pred"], field=field, party_fields=cfg.party_fields
            )
            pass_counts[result["pass_used"]] = pass_counts.get(result["pass_used"], 0) + 1
            row_d["fields"][field] = {
                "outcome": outcome,
                "gold": gold if _gt_ok(gold) else None,
                **result,
            }
        details.append(row_d)

    per_field = {
        f: {**stats[f], **_prf(stats[f]["tp"], stats[f]["fp"], stats[f]["fn"])} for f in fields
    }
    tp = sum(stats[f]["tp"] for f in fields)
    fp = sum(stats[f]["fp"] for f in fields)
    fn = sum(stats[f]["fn"] for f in fields)
    micro = _prf(tp, fp, fn)
    summary = {
        "pack": pack.name,
        "backend": args.backend,
        "model": args.model,
        "mode": "cascade_v2" if cascade else "oneshot_v1",
        "validate": validate,
        "concurrency": concurrency,
        "reasoning_effort": "none",
        "wall_seconds": round(wall_s, 2),
        "n_rows": len(rows),
        "n_llm_jobs": total,
        "fields": list(fields),
        "micro": micro,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "pass_counts": pass_counts,
        "per_field": per_field,
        "baselines": {
            "hybrid_gliner_qwen_allspans_micro_f1": ALLSPANS_MICRO,
            "unified_prompt_v2_micro_f1": PROMPT_V2_MICRO,
            "oracle_routing_micro_f1": ORACLE_MICRO,
        },
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out_dir / "details.json").write_text(json.dumps(details, indent=2), encoding="utf-8")
    with (out_dir / "per_field.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "field",
                "tp",
                "fp",
                "fn",
                "gt_present",
                "pred_present",
                "precision",
                "recall",
                "f1",
            ],
        )
        w.writeheader()
        for field in fields:
            row = per_field[field]
            w.writerow({"field": field, **{k: row[k] for k in w.fieldnames if k != "field"}})

    print(json.dumps(summary, indent=2), flush=True)
    print(
        f"micro_f1={micro.get('f1')}  vs_prompt_v2={PROMPT_V2_MICRO}  "
        f"vs_allspans={ALLSPANS_MICRO}  vs_oracle={ORACLE_MICRO}",
        flush=True,
    )
    print(f"wrote {out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
