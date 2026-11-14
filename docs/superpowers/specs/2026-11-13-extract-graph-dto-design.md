# Extract graph + DTO layer (design)

Status: approved by user in conversation ("implement it", 2026-11-13). Superseded in detail by the as-built §5 of `docs/action-pack-unified-extract.md`; see "As-built deviations" below.

## Intent
Move per-field extraction out of `scripts/eval_unified_field_qwen.py` into a typed Pydantic + LangGraph layer so that a new corporate action (tender, merger, rights, spin-off, ...) is a pack of config only. No graph, DTO or harness edits.

## Goals
- Event-agnostic graph, one invocation per field: retrieve -> prompt -> llm -> normalize -> validate.
- Typed DTOs at every boundary (`FieldExtractRequest`, `EvidenceBundle`, `FieldExtractResult`).
- `FieldPolicy` (pack-owned) generalizes `ClauseFieldSpec` and absorbs oneshot, cascade, clause, `_RULES_DIRECT_FIELDS` and Pass C as config.
- `EvidenceProvider` interface; one implementation (`ArtifactProvider`) reading existing preprocess artifacts + GT passages.
- Replay parity: graph predictions on the limit-20 holdout match `verify_c4_reasoning_none_limit20` (tolerance only for LLM nondeterminism).

## Non-goals
- Production / raw-filing input (eval only for now; a future `RawFilingProvider` plugs into the interface).
- Event-level graph replacing the eval loop.
- Changing scoring (`soft_match`) or backends.

## Anti-goals
- Any tender/merger string (SC TO-I, "If more than", ...) in graph, DTO or node code.
- Silent behaviour change: control flow changes must be proven by the replay test.

## Constraints
- `langgraph` is not installed; add to deps. Pydantic 2.13 present.
- Existing packs (`tender`, `merger`) must keep working; `--pack` CLI unchanged.

## Approaches considered
- A. Faithful port, generalize later: safest diff, but generalization tends not to happen.
- B. Policy-first graph (chosen): generic nodes + `FieldPolicy` from the start, guarded by a replay test.
- C. Event-level graph: rejected, couples graph to the eval loop.

## Design
Layout:
```
src/evaluation/extract/
  dtos.py        FieldExtractRequest, EvidenceBundle, FieldExtractResult
  policies.py    FieldPolicy (retrieve strategies, prompt_mode copy|pick|abstain,
                 null_if_empty, stop_at_first_hit, direct_from_rules, validate,
                 patterns/cues/max_chars)
  providers.py   EvidenceProvider protocol; ArtifactProvider
  graph.py       StateGraph wiring
  nodes/         retrieve, prompt, llm, normalize, validate
```
Mapping of today's behaviour to policy:
- clause: retrieve=[quotes, regex], copy, null_if_empty
- oneshot: retrieve=[rules, gliner, temporal], pick
- cascade A->B: retrieve=[[rules],[gliner,temporal]], stop_at_first_hit
- direct rules fields: direct_from_rules
- Pass C: validate

`ActionPack` gains `policies: dict[str, FieldPolicy]` with defaults derived from existing fields, so current packs run unchanged; `clause_fields` is converted to policies by an adapter. The eval script becomes: build request -> `graph.invoke` -> `soft_match`.

## Left to the builder
Exact DTO fields beyond those named, node-level error handling, how default policies are derived, test layout.

## As-built deviations
Implemented in `src/evaluation/extract/`; the design above changed in these ways:
- **`Stage` list, not flat `FieldPolicy` fields.** `FieldPolicy` is an ordered tuple of `Stage`s (`sources`, `prompt_mode`, `on_empty`, labels, `direct_from_rules`, `validate`) plus `stop_at_first_hit`. Cascade A->B, the merger inventory prior stage (`A_inventory`) and oneshot are all stage lists; `resolve_policy` derives them from legacy pack knobs.
- **Single `clause` source.** Clause evidence comes from `retrieve_clause` (quotes then regex, inside the existing pack function), not separate `quotes` / `regex` sources.
- **`Stage` and `FieldPolicy` are frozen dataclasses, not Pydantic.** A field named `validate` shadows `BaseModel.validate`. The DTOs stay Pydantic.
- **`PackHooks` and `EventContext.extras` added.** The merger harness carried pack-only logic (junk roles, span drops, rules prelude, inventory direct prior, synthesized spans). It lives in `PackHooks` on the pack, fed by `extras` (e.g. `primary_entity`, `is_proxy_filing`), so the graph stays event-agnostic. `extras` itself is derived by the pack's `extras_from_inventory` hook from the event's `inventory.json` (called by `ArtifactProvider`), and the prior-hit evidence line uses the pack's `prior_hint`.
- **Per-row context keys.** `ArtifactProvider` takes injected `event_id_for`, `temporal_for` and `key_for`; `req.accession` is the context key, so GT rows sharing an accession with different passages use per-row keys.
- **Graph targets the frozen 2026-11-13 snapshot, not the live script.** Parity is tested against a vendored copy of the legacy `extract_field` (`tests/evaluation/extract/legacy_extract.py`). The live `scripts/eval_unified_field_qwen.py` is edited separately and has since drifted (see "Known gaps / reconcile" in the unified-extract doc, §5.7); an xfail drift test flags it.
- **Validate gate.** Pass C runs when the field is in `validate_fields` (and validation is enabled), expressed as `Stage.validate` on derived stages.
- **Harness.** `scripts/eval_unified_field_graph.py` is the graph-based harness with the same CLI and outputs as the previous script. Per-pack harness settings (default `--gt`/`--out`, event-id strategy, party-name scoring fields) live in its `HARNESS_CONFIGS` (tender, merger); any other pack must pass `--gt` and `--out` (exit 2 otherwise) and uses the GT row's `event_id`.
- **Temporal lines for all date fields.** `ArtifactProvider.prepare` asks `temporal_for` for every `pack.date_fields` entry whenever any requested field is a date field, so the harness disk cache is never written from a `--fields` subset.
- **`stop_at_first_hit=False`.** A later null never erases an earlier hit; `evidence_final` stays the producing stage's evidence (derived policies all use `True`, so parity is unaffected).
