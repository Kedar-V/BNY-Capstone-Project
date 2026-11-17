#!/usr/bin/env python3
"""Build a frozen evidence pack (no LLM) for later multi-SLM replay.

Core path: route every field (Laya or heuristic) → freeze per-stage evidence so
``scripts/eval_from_evidence_pack.py`` can swap backends/models without re-running
retrieval, hybrid, or temporal NER.

  .venv/bin/python scripts/build_evidence_pack.py \\
      --pack tender --split holdout --router auto \\
      --pack-id tender_holdout_routed_hybrid

Progress bars on stderr (prepare + freeze). Ctrl-C pauses: cell checkpoint is
kept under the pack dir; re-run the same command to resume. ``--fresh`` discards it.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping

CHECKPOINT_JSONL = "_build_checkpoint.jsonl"
CHECKPOINT_META = "_build_meta.json"

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.action_packs import get_pack  # noqa: E402
from src.evaluation.experiments import ensure_holdout  # noqa: E402
from src.evaluation.extract.frozen import (  # noqa: E402
    FrozenFieldRecord,
    FrozenStage,
    build_manifest,
    write_evidence_pack,
)
from src.evaluation.extract.providers import (  # noqa: E402
    ArtifactProvider,
    build_bundle,
    context_n_rules,
    context_rules_direct,
)
from src.evaluation.extract.routing import (  # noqa: E402
    recipe_to_policy,
    route_fields,
)
from src.evaluation.llm_backends import load_dotenv  # noqa: E402
from src.evaluation.tender import load_gt  # noqa: E402
from src.preprocess.store import DEFAULT_PREPROCESS_ROOT, ArtifactStore  # noqa: E402


def _load_harness():
    spec = importlib.util.spec_from_file_location(
        "_eval_unified_field_graph_for_pack", ROOT / "scripts/eval_unified_field_graph.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


H = _load_harness()


def _default_pack_id(*, pack: str, split: str, routed: bool, hybrid: bool) -> str:
    mode = "routed" if routed else "oneshot"
    hy = "_hybrid" if hybrid else ""
    return f"{pack}_{split}_{mode}{hy}"


def _gold_cues(rows: list[dict], fields: tuple[str, ...], *, per_field: int = 3) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {f: [] for f in fields}
    for row in rows:
        for f in fields:
            if len(out[f]) >= per_field:
                continue
            g = (row.get(f) or "").strip()
            if g and g not in out[f]:
                out[f].append(g[:120])
    return out


def _checkpoint_meta(
    *,
    pack_id: str,
    routing_hash: str,
    accession_hash: str,
    fields: tuple[str, ...],
    cascade: bool,
    validate: bool,
    router_mode: str,
    n_rows: int,
) -> dict[str, Any]:
    return {
        "pack_id": pack_id,
        "routing_hash": routing_hash,
        "accession_hash": accession_hash,
        "fields": list(fields),
        "cascade": cascade,
        "validate": validate,
        "router_mode": router_mode,
        "n_rows": n_rows,
    }


def _load_checkpoint(
    out_dir: Path, expected: Mapping[str, Any], *, fresh: bool
) -> tuple[dict[tuple[int, str], FrozenFieldRecord], Path, Path]:
    """Return (done cells, jsonl path, meta path). Clears stale/fresh checkpoints."""
    ckpt = out_dir / CHECKPOINT_JSONL
    meta_path = out_dir / CHECKPOINT_META
    if fresh:
        for p in (ckpt, meta_path):
            if p.exists():
                p.unlink()
        return {}, ckpt, meta_path
    if not ckpt.exists() or not meta_path.exists():
        return {}, ckpt, meta_path
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        meta = {}
    if meta != expected:
        print(
            f"checkpoint meta mismatch — starting fresh "
            f"(had routing={meta.get('routing_hash')}, want {expected.get('routing_hash')})",
            file=sys.stderr,
            flush=True,
        )
        for p in (ckpt, meta_path):
            if p.exists():
                p.unlink()
        return {}, ckpt, meta_path
    done: dict[tuple[int, str], FrozenFieldRecord] = {}
    with ckpt.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = FrozenFieldRecord.from_dict(json.loads(line))
            done[(rec.ei, rec.field)] = rec
    print(
        f"resuming freeze: {len(done)} cells from {ckpt}",
        file=sys.stderr,
        flush=True,
    )
    return done, ckpt, meta_path


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser(description="Freeze ActionPack evidence for multi-SLM replay")
    p.add_argument("--gt", type=Path, default=None)
    p.add_argument("--out", type=Path, default=None, help="eval root (default from harness config)")
    p.add_argument("--pack", default="tender")
    p.add_argument("--documents-parquet", type=Path, default=ROOT / "data/processed/documents.parquet")
    p.add_argument("--split", choices=("holdout", "train"), default="holdout")
    p.add_argument("--accessions-file", type=Path, default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--fields", default="core", help="'core' or comma-separated subset")
    p.add_argument("--device", default="cpu")
    p.add_argument("--no-temporal", action="store_true")
    p.add_argument("--no-cascade", action="store_true", help="oneshot mixed evidence (default for packs)")
    p.add_argument("--validate", action="store_true", default=True)
    p.add_argument("--no-validate", action="store_true")
    p.add_argument(
        "--pack-id",
        default=None,
        help="directory name under <out>/evidence_packs/ (default: <pack>_<split>_<mode>[_hybrid])",
    )
    p.add_argument(
        "--bm25-only",
        action="store_true",
        help="disable dense hybrid at build time (faster; BM25 still runs if pack.hybrid is set)",
    )
    p.add_argument(
        "--router",
        choices=("auto", "laya", "heuristic"),
        default="auto",
        help="per-field evidence router (auto=Laya if LAYA_* set, else heuristic/oracle)",
    )
    p.add_argument(
        "--noul-threshold",
        type=float,
        default=0.5,
        help="Laya noul threshold for including an evidence leg",
    )
    p.add_argument(
        "--fresh",
        action="store_true",
        help="ignore any pause checkpoint and rebuild freeze from scratch",
    )
    p.add_argument(
        "--no-progress",
        action="store_true",
        help="disable tqdm progress bars on stderr",
    )
    args = p.parse_args(argv)

    try:
        pack = get_pack(args.pack)
    except KeyError as e:
        print(str(e), file=sys.stderr)
        return 2

    if args.bm25_only and pack.hybrid is not None:
        import dataclasses

        pack = dataclasses.replace(
            pack, hybrid=dataclasses.replace(pack.hybrid, use_dense=False)
        )

    cfg = H.HARNESS_CONFIGS.get(pack.name)
    if cfg is None:
        if args.gt is None or args.out is None:
            print(
                f"pack={pack.name!r} has no harness config; pass both --gt and --out",
                file=sys.stderr,
            )
            return 2
        cfg = H.HarnessConfig(gt=str(args.gt), out=str(args.out))
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
    pack_id = args.pack_id or _default_pack_id(
        pack=pack.name, split=args.split, routed=True, hybrid=pack.hybrid_enabled
    )

    store = ArtifactStore(pack.name, DEFAULT_PREPROCESS_ROOT)
    _tagger_holder: dict[str, Any] = {"pipe": None}

    def _ensure_tagger():
        if args.no_temporal:
            return None
        if _tagger_holder["pipe"] is None:
            from transformers import pipeline

            print(f"loading temporal tagger on {args.device}…", flush=True)
            _tagger_holder["pipe"] = pipeline(
                "token-classification",
                model=H.TEMPORAL_MODEL,
                aggregation_strategy="simple",
                device=args.device,
            )
        return _tagger_holder["pipe"]

    gt_rows = load_gt(args.gt)
    accessions_all = sorted({H._acc(r) for r in gt_rows if r.get("accession_number")})
    holdout = set(ensure_holdout(args.out, accessions_all, n=20))
    if args.split == "holdout":
        rows = [r for r in gt_rows if H._acc(r) in holdout]
    else:
        rows = [r for r in gt_rows if H._acc(r) not in holdout]
    if args.accessions_file is not None:
        try:
            wanted = H.read_accessions_file(args.accessions_file)
        except OSError as e:
            print(f"cannot read --accessions-file: {e}", file=sys.stderr)
            return 2
        rows = [r for r in rows if H._acc(r) in wanted]
        if not rows:
            print("no GT rows match --accessions-file for this split", file=sys.stderr)
            return 2
    if args.limit:
        rows = rows[: args.limit]

    event_id_for = cfg.event_ids(rows, args.documents_parquet)
    row_keys = {id(r): f"{H._acc(r)}#{i}" for i, r in enumerate(rows)}
    temporal_dir = args.out / "temporal_cache" / pack.name
    temporal_dir.mkdir(parents=True, exist_ok=True)
    temporal_for = H.DiskTemporalCache(pack, temporal_dir, _ensure_tagger)
    provider = ArtifactProvider(
        pack,
        store,
        event_id_for=event_id_for,
        temporal_for=temporal_for,
        key_for=lambda r: row_keys[id(r)],
    )

    # --- core: route every field before freezing evidence ----------------------------
    gold_cues = _gold_cues(rows, fields)
    recipes = route_fields(
        pack,
        fields,
        mode=args.router,
        gold_cues=gold_cues,
        noul_threshold=float(args.noul_threshold),
    )
    policies = {
        f: recipe_to_policy(pack, recipes[f], validate=validate) for f in fields
    }
    router_used = (
        "laya"
        if any(r.source == "laya" for r in recipes.values())
        else "heuristic"
    )
    recipe_summary = {f: recipes[f].to_dict() for f in fields}
    routing_blob = json.dumps(recipe_summary, sort_keys=True)
    routing_hash = hashlib.sha256(routing_blob.encode("utf-8")).hexdigest()[:16]

    print(
        json.dumps(
            {
                "pack": pack.name,
                "pack_id": pack_id,
                "router": router_used,
                "router_mode": args.router,
                "cascade": cascade,
                "validate": validate,
                "hybrid": pack.hybrid_enabled,
                "n_rows": len(rows),
                "fields": list(fields),
                "recipes": {
                    f: {"shape": recipes[f].shape, "legs": sorted(recipes[f].legs)}
                    for f in fields
                },
            },
            indent=2,
        ),
        flush=True,
    )
    from tqdm import tqdm

    from src.evaluation.extract.dtos import FieldExtractRequest

    show_progress = not args.no_progress
    acc_list = [H._acc(r) for r in rows]
    accession_hash = hashlib.sha256("\n".join(acc_list).encode("utf-8")).hexdigest()[:16]
    out_dir = args.out / "evidence_packs" / pack_id
    out_dir.mkdir(parents=True, exist_ok=True)

    expected_meta = _checkpoint_meta(
        pack_id=pack_id,
        routing_hash=routing_hash,
        accession_hash=accession_hash,
        fields=fields,
        cascade=cascade,
        validate=validate,
        router_mode=args.router,
        n_rows=len(rows),
    )
    done, ckpt_path, meta_path = _load_checkpoint(
        out_dir, expected_meta, fresh=bool(args.fresh)
    )
    if not done:
        meta_path.write_text(json.dumps(expected_meta, indent=2), encoding="utf-8")
        if ckpt_path.exists() and args.fresh:
            pass  # already cleared
        elif not ckpt_path.exists():
            ckpt_path.write_text("", encoding="utf-8")

    print(f"temporal+load: preparing {len(rows)} rows…", file=sys.stderr, flush=True)
    keys = provider.prepare(rows, fields, progress=show_progress)
    print(
        f"temporal_cache hits={temporal_for.hits} misses={temporal_for.misses}",
        flush=True,
    )

    records_by_cell: dict[tuple[int, str], FrozenFieldRecord] = dict(done)
    n_stages = 0
    n_empty_stages = 0
    for rec in done.values():
        n_stages += len(rec.stages)
        n_empty_stages += sum(1 for s in rec.stages if s.empty)

    n_cells = len(rows) * len(fields)
    freeze_bar = tqdm(
        total=n_cells,
        initial=len(done),
        desc="freeze",
        unit="cell",
        file=sys.stderr,
        dynamic_ncols=True,
        disable=not show_progress,
    )
    paused = False
    try:
        with ckpt_path.open("a", encoding="utf-8") as ckpt_fh:
            for ei, row in enumerate(rows):
                key = keys[ei]
                ctx = None
                acc = H._acc(row)
                for field in fields:
                    cell = (ei, field)
                    if cell in records_by_cell:
                        continue  # already in bar via initial=len(done)
                    if ctx is None:
                        ctx = provider.context(
                            FieldExtractRequest(
                                pack_name=pack.name,
                                field=fields[0],
                                event_id=None,
                                accession=key,
                                model="freeze",
                                validate_enabled=validate,
                                cascade=cascade,
                            )
                        )
                    policy = policies[field]
                    stages: list[FrozenStage] = []
                    for stage in policy.stages:
                        bundle = build_bundle(pack, ctx, field, stage.sources)
                        stages.append(
                            FrozenStage(
                                name=stage.name,
                                sources=stage.sources,
                                prompt_mode=stage.prompt_mode,
                                on_empty=stage.on_empty,
                                direct_from_rules=stage.direct_from_rules,
                                empty=bundle.empty,
                                text=bundle.text,
                                source=bundle.source,
                                n_chars=bundle.n_chars,
                                validate=stage.validate,
                                pass_label=stage.pass_label,
                                null_label=stage.null_label,
                                empty_label=stage.empty_label,
                                direct_label=stage.direct_label,
                            )
                        )
                        n_stages += 1
                        if bundle.empty:
                            n_empty_stages += 1
                    rec = FrozenFieldRecord(
                        ei=ei,
                        accession=acc,
                        key=key,
                        event_id=ctx.event_id,
                        field=field,
                        gold=(row.get(field) or "").strip(),
                        stages=tuple(stages),
                        rules_direct=tuple(context_rules_direct(pack, ctx, field)),
                        extras=dict(ctx.extras),
                        n_rules=context_n_rules(pack, ctx, field),
                    )
                    records_by_cell[cell] = rec
                    ckpt_fh.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")
                    ckpt_fh.flush()
                    freeze_bar.set_postfix_str(f"{acc[:14]} {field}", refresh=False)
                    freeze_bar.update(1)
    except KeyboardInterrupt:
        paused = True
        print(
            f"\npaused at {len(records_by_cell)}/{n_cells} cells — "
            f"re-run the same command to resume (or --fresh to restart).\n"
            f"checkpoint: {ckpt_path}",
            file=sys.stderr,
            flush=True,
        )
    finally:
        freeze_bar.close()

    if paused:
        return 130

    # Stable order: row order × field order
    records = [
        records_by_cell[(ei, f)]
        for ei in range(len(rows))
        for f in fields
        if (ei, f) in records_by_cell
    ]
    if len(records) != n_cells:
        print(
            f"incomplete freeze: {len(records)}/{n_cells} cells; not writing final pack",
            file=sys.stderr,
        )
        return 1

    manifest = build_manifest(
        pack_id=pack_id,
        pack=pack,
        fields=fields,
        cascade=cascade,
        validate=validate,
        split=args.split,
        n_rows=len(rows),
        accessions=acc_list,
        accession_hash=accession_hash,
        limit=args.limit,
        router=router_used,
        routing_hash=routing_hash,
    )
    write_evidence_pack(out_dir, manifest=manifest, records=records)
    (out_dir / "routing.json").write_text(
        json.dumps(
            {
                "router": router_used,
                "router_mode": args.router,
                "noul_threshold": float(args.noul_threshold),
                "routing_hash": routing_hash,
                "fields": recipe_summary,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    for p in (ckpt_path, meta_path):
        if p.exists():
            p.unlink()
    print(
        json.dumps(
            {
                "wrote": str(out_dir),
                "n_records": len(records),
                "n_stages": n_stages,
                "n_empty_stages": n_empty_stages,
                "accession_hash": accession_hash,
                "router": router_used,
                "routing_hash": routing_hash,
            },
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
