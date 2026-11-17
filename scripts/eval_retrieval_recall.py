#!/usr/bin/env python3
"""Evidence recall of an ActionPack's retrieval, without any LLM call.

For every GT row of a split and every requested field, builds the evidence the extract
graph would show the model (``ArtifactProvider`` + the field's resolved policy) and asks
whether the gold answer is reachable in it, with the reachability logic of
``scripts/analyze_input_quality.py`` (dates: strict month/day/year).

Evidence = that of the FIRST stage that fires, as the graph would run it without an LLM
answer: a stage whose bundle is empty is skipped (``on_empty=skip``), ends the policy with
no evidence (``on_empty=null``) or is shown empty (``on_empty=ask``); the first non-empty
stage is what the model sees first. ``recall_any_stage`` also counts gold reachable in a
LATER stage's evidence (reached when the first stage's LLM call returns null).

Per field: rows with gold, evidence-empty rate, recall, strict recall (gold's alphanumeric
text verbatim in the evidence; dates: strict m/d/y), any-stage recall, avg evidence chars,
and ``recall_ext``: dates strict m/d/y; other fields a contiguous run of >= half of gold's
tokens verbatim in the evidence (``recall`` uses the scorer's soft matcher, which accepts
any listed candidate that is a substring of gold, e.g. "Shares", but rejects a long copied
excerpt that contains gold among other text) or, for an absence label "No <noun> ...", a
negation of that noun in the evidence. ``recall_piece`` = ``recall`` or, for a clause
excerpt, one copy-shaped piece of it (split at parentheses / sentence ends) passes the
scorer's matcher.

Splits (tender: rows of the GT CSV; holdout = ``<out>/experiments/holdout_accessions.txt``):
  holdout   the inspected holdout (SEALED)
  confirm   ``<out>/experiments/confirm_accessions.txt``: the first 20 non-holdout
            accessions with preprocess artifacts, sorted by sha256(accession) (SEALED;
            create it with ``--write-confirm-set``)
  dev       every other non-holdout accession with preprocess artifacts whose preprocess
            event does not also back a confirm / holdout accession (event-disjoint)

Sealed splits run only with ``--sealed --out FILE``: aggregates only (no per-row output,
no gold), and at most once per output file (a ``FILE.sealed`` marker is written first).

  .venv/bin/python scripts/eval_retrieval_recall.py --pack tender --split dev \\
      --fields minimum_tender_condition,security_description --show-rows
  .venv/bin/python scripts/eval_retrieval_recall.py --pack tender --split dev --pattern-counts
  .venv/bin/python scripts/eval_retrieval_recall.py --pack tender --split confirm \\
      --fields core --sealed --out outputs/tender_eval/experiments/recall_confirm_after.json
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.action_packs import get_pack  # noqa: E402
from src.evaluation.action_packs.base import ActionPack  # noqa: E402
from src.evaluation.extract.policies import FieldPolicy, resolve_policy  # noqa: E402
from src.evaluation.extract.providers import (  # noqa: E402
    CLAUSE_PREFIX,
    ArtifactProvider,
    EventContext,
    build_bundle,
)
from src.evaluation.tender import load_gt, normalize  # noqa: E402
from src.preprocess.store import DEFAULT_PREPROCESS_ROOT, ArtifactStore  # noqa: E402

SEALED_SPLITS = frozenset({"holdout", "confirm"})
CONFIRM_N = 20
TEMPORAL_MODEL = "satyaalmasian/temporal_tagger_BERT_tokenclassifier"
_ALNUM = re.compile(r"[^a-z0-9]+")


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(f"_{name}_for_recall", ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


H = _load_script("eval_unified_field_graph")
AIQ = _load_script("analyze_input_quality")


# --- splits --------------------------------------------------------------------------


def holdout_file(out: Path) -> Path:
    return out / "experiments" / "holdout_accessions.txt"


def confirm_file(out: Path) -> Path:
    return out / "experiments" / "confirm_accessions.txt"


def sha_order(accessions) -> list[str]:
    return sorted(accessions, key=lambda a: hashlib.sha256(a.encode("utf-8")).hexdigest())


def train_with_artifacts(gt_rows: list[dict], holdout: set[str], event_id_for, store: ArtifactStore) -> set[str]:
    out: set[str] = set()
    for r in gt_rows:
        acc = H._acc(r)
        if not acc or acc in holdout:
            continue
        eid = event_id_for(r)
        if eid and store.segments_path(eid).exists():
            out.add(acc)
    return out


def split_accessions(split: str, *, gt_rows, out: Path, event_id_for, store) -> set[str]:
    hold = H.read_accessions_file(holdout_file(out))
    if split == "holdout":
        return hold
    conf_path = confirm_file(out)
    if not conf_path.exists():
        raise SystemExit(f"{conf_path} missing: create it with --write-confirm-set")
    conf = H.read_accessions_file(conf_path)
    if split == "confirm":
        return conf
    # Event-disjoint dev: accessions of one tender offer (original + amendments) share a
    # preprocess event, hence the same excerpts / segments. Drop every train accession
    # whose event also backs a sealed (confirm / holdout) accession.
    eid_by_acc = {H._acc(r): event_id_for(r) for r in gt_rows if H._acc(r)}
    sealed_events = {eid_by_acc.get(a) for a in hold | conf} - {None}
    return {
        a
        for a in train_with_artifacts(gt_rows, hold, event_id_for, store) - conf
        if eid_by_acc.get(a) not in sealed_events
    }


# --- evidence per policy ---------------------------------------------------------------


def stage_evidence(pack: ActionPack, ctx: EventContext, field: str, policy: FieldPolicy):
    """(first-firing stage name, its evidence, all non-empty stages' evidence)."""
    first: tuple[str, str] | None = None
    every: list[str] = []
    for stage in policy.stages:
        if "prior" in stage.sources and (
            pack.hooks is None
            or pack.hooks.direct_prior is None
            or pack.hooks.direct_prior(field, ctx.extras) is None
        ):
            continue
        b = build_bundle(pack, ctx, field, stage.sources)
        if not b.empty:
            every.append(b.text)
        if first is None:
            if b.empty and stage.on_empty == "skip":
                continue
            if b.empty and stage.on_empty == "null":
                first = (stage.name, "")
                break  # ends the whole policy
            first = (stage.name, b.text)
    if first is None:
        first = ("none", "")
    return first[0], first[1], every


def _strict_in(field: str, gold: str, ev: str, date_fields) -> bool:
    if field in date_fields:
        g = AIQ.strict_dates(gold)
        return bool(g and g & AIQ.strict_dates(ev))
    g = _ALNUM.sub(" ", normalize(gold)).strip()
    return bool(g) and g in _ALNUM.sub(" ", normalize(ev))


_NEG = r"\b(?:not|no|without|neither|nor|none)\b"


def _span_in(gold: str, ev: str) -> bool:
    """A contiguous run of >= half of gold's alphanumeric tokens (min 3, or all of a
    shorter gold) occurs verbatim in ``ev``. Fairer than ``recall`` for long copied
    excerpts (the soft matcher wants gold inside ONE candidate, or a candidate inside gold)."""
    g = _ALNUM.sub(" ", normalize(gold)).split()
    if not g:
        return False
    e = " " + " ".join(_ALNUM.sub(" ", normalize(ev)).split()) + " "
    need = min(len(g), max(3, (len(g) + 1) // 2))
    return any(" " + " ".join(g[i : i + need]) + " " in e for i in range(len(g) - need + 1))


def _absence_in(gold: str, ev: str) -> bool:
    """Gold of the form "No <noun> ..." (an absence label) and the evidence negates that
    noun within 80 chars ("not conditioned on any minimum number")."""
    m = re.match(r"\s*no\s+([a-z][a-z\-]{2,})", gold or "", flags=re.I)
    if not m:
        return False
    return re.search(_NEG + r"[^.]{0,80}?\b" + re.escape(m.group(1).lower()), ev or "", flags=re.I) is not None


def _reach_ext(field: str, gold: str, ev: str, date_fields) -> bool:
    """recall_ext: dates strict m/d/y; else contiguous-span match or absence statement."""
    if field in date_fields and AIQ.strict_dates(gold):
        return bool(AIQ.strict_dates(gold) & AIQ.strict_dates(ev))
    return _span_in(gold, ev) or _absence_in(gold, ev)


_PIECE_SPLIT = re.compile(r"[()]|\n---\n|(?<=[.;])\s+|_{3,}")


def _piece_in(field: str, gold: str, ev: str, match, date_fields) -> bool:
    """recall_piece: a copy-shaped candidate of a CLAUSE excerpt satisfies the scorer's
    matcher. The excerpt is cut at parentheses (cover-page captions), hit separators and
    sentence ends; pieces of >= 3 tokens are scored like a predicted value would be."""
    if field in date_fields or not ev.startswith(CLAUSE_PREFIX):
        return False
    for piece in _PIECE_SPLIT.split(ev[len(CLAUSE_PREFIX):]):
        if len(_ALNUM.sub(" ", piece.lower()).split()) >= 3 and match(piece.strip(), gold):
            return True
    return False


def measure(pack: ActionPack, provider: ArtifactProvider, rows: list[dict], keys: list[str],
            fields: tuple[str, ...], *, cascade: bool, party_fields) -> tuple[dict, list[dict]]:
    agg: dict[str, dict[str, Any]] = {}
    per_row: list[dict] = []
    for field in fields:
        policy = resolve_policy(pack, field, cascade=cascade)
        match = H._party_soft_match if field in party_fields else H.soft_match
        c: Counter = Counter()
        stages: Counter = Counter()
        chars = 0
        for row, key in zip(rows, keys):
            gold = (row.get(field) or "").strip()
            if not H._gt_ok(gold):
                continue
            ctx = provider._contexts[key]
            stage, ev, every = stage_evidence(pack, ctx, field, policy)
            cat = AIQ.reachability(field, gold, ev, match, pack.date_fields)
            reach = cat in AIQ.REACHABLE
            strict = reach and _strict_in(field, gold, ev, pack.date_fields)
            any_stage = reach or any(
                AIQ.reachability(field, gold, e, match, pack.date_fields) in AIQ.REACHABLE
                for e in every
            )
            piece = reach or _piece_in(field, gold, ev, match, pack.date_fields)
            ext = bool(ev) and _reach_ext(field, gold, ev, pack.date_fields)
            ext_any = ext or any(_reach_ext(field, gold, e, pack.date_fields) for e in every)
            c["n"] += 1
            c["empty"] += cat == AIQ.CATEGORIES[1]
            c["reach"] += reach
            c["strict"] += strict
            c["any"] += any_stage
            c["ext"] += ext
            c["piece"] += piece
            c["ext_any"] += ext_any
            stages[stage] += 1
            chars += len(ev)
            per_row.append({"accession": H._acc(row), "key": key, "field": field, "stage": stage,
                            "category": cat, "reachable": reach, "strict": strict,
                            "any_stage": any_stage, "piece": piece, "ext": ext, "ext_any": ext_any,
                            "n_chars": len(ev), "gold": gold})
        n = c["n"]
        agg[field] = {
            "rows_with_gold": n,
            "evidence_empty_rate": round(c["empty"] / n, 4) if n else None,
            "recall": round(c["reach"] / n, 4) if n else None,
            "recall_strict": round(c["strict"] / n, 4) if n else None,
            "recall_any_stage": round(c["any"] / n, 4) if n else None,
            "recall_piece": round(c["piece"] / n, 4) if n else None,
            "recall_ext": round(c["ext"] / n, 4) if n else None,
            "recall_ext_any_stage": round(c["ext_any"] / n, 4) if n else None,
            "avg_evidence_chars": round(chars / n, 1) if n else None,
            "first_stage": dict(sorted(stages.items())),
        }
    return agg, per_row


# --- per-pattern match counts (dev only) ------------------------------------------------


def _clause_blob(ctx: EventContext) -> str:
    """The text ``retrieve_clause`` runs its regexes over (whitespace collapsed)."""
    from src.evaluation.action_packs.retrieve import _all_passage_text

    blob = "\n".join(x for x in (_all_passage_text(ctx.passages), ctx.doc_text or ctx.excerpts, ctx.excerpts) if x)
    return re.sub(r"\s+", " ", blob)


def pattern_counts(pack: ActionPack, provider: ArtifactProvider, rows, keys) -> dict:
    """Distinct filings (accessions) and preprocess events whose clause blob each pattern matches."""
    out: dict[str, list[dict]] = {}
    for field, spec in pack.clause_fields.items():
        res = []
        for i, pat in enumerate(spec.patterns):
            rx = re.compile(pat, flags=re.I | re.S)
            hit_accs, hit_events = set(), set()
            for row, key in zip(rows, keys):
                ctx = provider._contexts[key]
                if rx.search(_clause_blob(ctx)):
                    hit_accs.add(H._acc(row))
                    hit_events.add(ctx.event_id)
            res.append({"pattern_index": i, "distinct_filings": len(hit_accs),
                        "distinct_events": len(hit_events), "pattern": pat})
        out[field] = res
    return out


# --- CLI -------------------------------------------------------------------------------


def _print_table(agg: dict) -> None:
    cols = ("rows_with_gold", "evidence_empty_rate", "recall", "recall_strict", "recall_any_stage",
            "recall_piece", "recall_ext", "recall_ext_any_stage", "avg_evidence_chars")
    short = ("n_gold", "empty", "recall", "strict", "any_stage", "piece", "ext", "ext_any", "avg_chars")
    print(f"{'field':26s}" + "".join(f"{c:>10s}" for c in short) + "  first_stage")
    for field, a in agg.items():
        vals = "".join(f"{'-' if a[c] is None else a[c]!s:>10s}" for c in cols)
        print(f"{field:26s}{vals}  {a['first_stage']}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--pack", default="tender")
    p.add_argument("--split", choices=("dev", "confirm", "holdout"), required=True)
    p.add_argument("--fields", default="core", help="'core' or comma-separated subset")
    p.add_argument("--sealed", action="store_true", help="aggregate-only, once per --out file")
    p.add_argument("--out", type=Path, default=None, help="write the JSON result here")
    p.add_argument("--cascade", action="store_true", help="resolve cascade policies (default oneshot)")
    p.add_argument("--gt", type=Path, default=None)
    p.add_argument("--eval-out", type=Path, default=None, help="pack eval dir (default from harness config)")
    p.add_argument("--documents-parquet", type=Path, default=ROOT / "data/processed/documents.parquet")
    p.add_argument("--no-temporal", action="store_true", help="temporal cache hits only, never run the tagger")
    p.add_argument("--device", default="cpu")
    p.add_argument("--show-rows", action="store_true", help="dev only: per-row diagnostics")
    p.add_argument("--pattern-counts", action="store_true", help="dev only: distinct filings per clause pattern")
    p.add_argument("--write-confirm-set", action="store_true",
                   help="write confirm_accessions.txt (ids only) if absent, then exit")
    args = p.parse_args(argv)

    pack = get_pack(args.pack)
    cfg = H.HARNESS_CONFIGS.get(pack.name)
    if cfg is None and (args.gt is None or args.eval_out is None):
        print(f"pack {pack.name!r} has no harness config: pass --gt and --eval-out", file=sys.stderr)
        return 2
    gt_path = args.gt or ROOT / cfg.gt
    eval_out = args.eval_out or ROOT / cfg.out
    party = cfg.party_fields if cfg else frozenset()
    event_ids = cfg.event_ids if cfg else H.generic_event_ids
    sealed_split = args.split in SEALED_SPLITS
    marker: Path | None = None
    if not args.write_confirm_set:
        if sealed_split and not args.sealed:
            print(f"split {args.split!r} is sealed: run with --sealed --out FILE", file=sys.stderr)
            return 2
        if args.sealed:
            if args.out is None:
                print("--sealed needs --out FILE", file=sys.stderr)
                return 2
            if args.show_rows or args.pattern_counts:
                print("--sealed prints aggregates only (no --show-rows / --pattern-counts)",
                      file=sys.stderr)
                return 2
            marker = args.out.with_name(args.out.name + ".sealed")
            if marker.exists() or args.out.exists():
                print(f"sealed pass already run for {args.out} ({marker}); refusing", file=sys.stderr)
                return 2

    gt_rows = load_gt(gt_path)
    store = ArtifactStore(pack.name, DEFAULT_PREPROCESS_ROOT)
    event_id_for = event_ids(gt_rows, args.documents_parquet)

    if args.write_confirm_set:
        path = confirm_file(eval_out)
        if path.exists():
            print(f"{path} exists; not rewriting", file=sys.stderr)
            return 2
        hold = H.read_accessions_file(holdout_file(eval_out))
        train = train_with_artifacts(gt_rows, hold, event_id_for, store)
        conf = sha_order(train)[:CONFIRM_N]
        path.write_text("\n".join(conf) + "\n", encoding="utf-8")
        print(f"wrote {len(conf)} confirm accessions (of {len(train)} train with artifacts) to {path}")
        return 0

    if args.fields.strip().lower() == "core":
        fields = pack.fields
    else:
        fields = tuple(f.strip() for f in args.fields.split(",") if f.strip())
        bad = [f for f in fields if f not in pack.field_defs]
        if bad:
            print(f"unknown fields for pack={pack.name}: {bad}", file=sys.stderr)
            return 2

    if marker is not None:
        # written BEFORE measuring: a crashed or interrupted sealed pass still counts as used
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"split": args.split, "pack": pack.name}) + "\n", encoding="utf-8")

    accs = split_accessions(args.split, gt_rows=gt_rows, out=eval_out, event_id_for=event_id_for, store=store)
    rows = [r for r in gt_rows if H._acc(r) in accs]

    holder: dict[str, Any] = {"pipe": None}

    def tagger_loader():
        if args.no_temporal:
            return None
        if holder["pipe"] is None:
            from transformers import pipeline

            print(f"loading temporal tagger on {args.device}…", file=sys.stderr, flush=True)
            holder["pipe"] = pipeline("token-classification", model=TEMPORAL_MODEL,
                                      aggregation_strategy="simple", device=args.device)
        return holder["pipe"]

    temporal = H.DiskTemporalCache(pack, eval_out / "temporal_cache" / pack.name, tagger_loader)
    row_keys = {id(r): f"{H._acc(r)}#{i}" for i, r in enumerate(rows)}
    provider = ArtifactProvider(pack, store, event_id_for=event_id_for, temporal_for=temporal,
                                key_for=lambda r: row_keys[id(r)])
    keys = provider.prepare(rows, fields)
    agg, per_row = measure(pack, provider, rows, keys, fields, cascade=args.cascade, party_fields=party)

    result: dict[str, Any] = {
        "pack": pack.name,
        "split": args.split,
        "mode": "cascade" if args.cascade else "oneshot",
        "n_accessions": len({H._acc(r) for r in rows}),
        "n_rows": len(rows),
        "temporal_scan_chars": pack.temporal_scan_chars,
        "temporal_max_spans": pack.temporal_max_spans,
        "temporal_cache": {"hits": temporal.hits, "misses": temporal.misses},
        "fields": agg,
    }
    if args.pattern_counts and not sealed_split:
        result["pattern_counts"] = pattern_counts(pack, provider, rows, keys)
    if not sealed_split:
        result["rows"] = [{k: v for k, v in r.items() if k != "gold"} for r in per_row]

    print(f"pack={pack.name} split={args.split} accessions={result['n_accessions']} rows={len(rows)} "
          f"scan={pack.temporal_scan_chars}/{pack.temporal_max_spans}")
    _print_table(agg)
    if args.show_rows and not sealed_split:
        for r in per_row:
            print(f"  {r['accession']} {r['field']:24s} stage={r['stage']:8s} reach={int(r['reachable'])} "
                  f"strict={int(r['strict'])} any={int(r['any_stage'])} ext={int(r['ext'])} "
                  f"ext_any={int(r['ext_any'])} chars={r['n_chars']:6d} "
                  f"{r['category']!r} gold={r['gold'][:70]!r}")
    if "pattern_counts" in result:
        for field, res in result["pattern_counts"].items():
            for r in res:
                print(f"  pattern {field}[{r['pattern_index']}]: {r['distinct_filings']} distinct filings, "
                      f"{r['distinct_events']} distinct events")
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
