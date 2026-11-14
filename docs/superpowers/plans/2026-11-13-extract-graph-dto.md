# Extract graph + DTO layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the per-field extract logic in `scripts/eval_unified_field_qwen.py` with an event-agnostic LangGraph + Pydantic layer driven by pack-owned `FieldPolicy` config, with proven prediction parity.

**Architecture:** One compiled LangGraph per `(pack, backend, provider)`, invoked once per field. Nodes loop over policy *stages* (retrieve -> prompt -> llm), then normalize -> validate. Evidence comes from an `EvidenceProvider` (only `ArtifactProvider` now). Oneshot, cascade, clause, direct-rules and Pass C are all expressed as policy data, never as graph branches on event type.

**Tech Stack:** Python, Pydantic v2 (2.13 installed), `langgraph` (add), pytest.

**Spec:** `docs/superpowers/specs/2026-11-13-extract-graph-dto-design.md`. The legacy behaviour to preserve is `extract_field` in `scripts/eval_unified_field_qwen.py` (read it before Tasks 1, 3, 4).

## Global Constraints

- No tender/merger strings (SC TO-I, "If more than", "proration", ...) in `src/evaluation/extract/`. They live only in packs.
- `--pack`, `--no-cascade`, `--validate/--no-validate`, `--no-temporal` CLI behaviour and the run output JSON shape stay unchanged.
- `scripts/eval_temporal_tagger_dates.py` is not moved or edited.
- Do not commit: the working tree holds unrelated uncommitted changes. Leave commits to the user.
- Run tests with `.venv/bin/python -m pytest tests/evaluation/extract -v`.

## Review Focus

- Event with no artifacts (empty rep/spans/excerpts/passages): result is `pred=None`, no exception (Task 3 test).
- Backend raises mid-graph: result `pass_used="error"`, `pred=None`, message in `raw_llm` (Task 3 test).
- LLM returns malformed JSON, fenced JSON or `<think>` blocks: parsed or null, never raises (Task 2 test).
- Non-date field never touches the temporal tagger or emits TEMPORAL evidence even if a policy lists `temporal` (Task 3 test).
- New pack with a field that has no hints, defs or policy: derives a default policy, no `KeyError` (Task 1 and Task 5 tests).
- Shared compiled graph invoked from a `ThreadPoolExecutor` (Task 3 test).

---

### Task 1: DTOs, `FieldPolicy`, pack integration

**Files:**
- Create: `src/evaluation/extract/__init__.py`, `src/evaluation/extract/dtos.py`, `src/evaluation/extract/policies.py`
- Modify: `src/evaluation/action_packs/base.py` (add `policies: dict[str, FieldPolicy]` default `{}`), `requirements.txt` (`langgraph>=0.2`, `pydantic>=2.5`)
- Test: `tests/evaluation/extract/test_policies.py`

**Interfaces:**
- Produces (`dtos.py`):
  - `FieldExtractRequest(pack_name: str, field: str, event_id: str | None, accession: str, model: str, validate_enabled: bool, cascade: bool)`
  - `EvidenceBundle(text: str, source: Literal["clause","rules","gliner","temporal","mixed"], n_chars: int, empty: bool)`
  - `FieldExtractResult(pred: str | None, pass_used: str, n_evidence_chars: int, n_rules: int, raw_llm: str, validate_verdict: bool | None = None)`
- Produces (`policies.py`):
  - `Stage(name: str, sources: tuple[str, ...], prompt_mode: Literal["copy","pick"], on_empty: Literal["null","skip","ask"], pass_label: str, null_label: str | None, direct_from_rules: bool, validate: bool)`. `sources` values are `clause|rules|gliner|temporal`. `null_label=None` means "keep the previous `pass_used`" (cascade Pass A).
  - `FieldPolicy(stages: tuple[Stage, ...], stop_at_first_hit: bool = True)`
  - `resolve_policy(pack: ActionPack, field: str, *, cascade: bool) -> FieldPolicy`: returns `pack.policies[field]` if present, else derives from legacy knobs.
- Pack `ClauseFieldSpec` stays (it supplies patterns/prompt/max_chars); it is referenced from the clause stage by field name, not copied.

- [ ] **Step 1: Write failing tests** in `test_policies.py` using small fake `ActionPack`s built inline (one with `clause_fields`, one without):
  - `test_clause_field_resolves_single_clause_stage`: stages == 1, sources == ("clause",), `on_empty == "null"`, `pass_label == "clause"`, `null_label == "clause_null"`, `validate` only if field in `validate_fields`.
  - `test_oneshot_policy_for_date_field_includes_temporal`: `cascade=False`, date field -> sources `("rules","gliner","temporal")`, `on_empty == "ask"`, `pass_label == "oneshot"`, `validate=True`; non-date field -> `("rules","gliner")`.
  - `test_cascade_policy_has_rules_then_span_stage`: stage 0 sources `("rules",)`, `on_empty == "skip"`, `pass_label == "A"`, `null_label is None`, `validate == (field in validate_fields)`; stage 1 sources `("gliner",)` or `("gliner","temporal")` for date fields, `pass_label == "B"`, `null_label == "B_null"`, `validate=True`.
  - `test_identifier_fields_are_direct_from_rules`: `ticker`, `cusip`, `isin` get `direct_from_rules=True` on the rules stage, `pass_label` for the direct hit is `"A_rules"` (stage field `direct_label: str = "A_rules"`; add it to `Stage`).
  - `test_pack_policy_overrides_derivation` and `test_unknown_field_without_defs_derives_default` (field absent from `field_defs`/`hint_allow` -> no exception).
  - `test_request_rejects_blank_field` (pydantic validation).

- [ ] **Step 2: Run to verify failure:** `.venv/bin/python -m pytest tests/evaluation/extract/test_policies.py -v` -> FAIL (module missing).

- [ ] **Step 3: Implement** the DTOs and policy module. DTOs are frozen Pydantic v2 models. The set of direct-from-rules identifier fields moves out of the script into the derivation as a module constant `DIRECT_RULES_FIELDS = frozenset({"ticker","cusip","isin"})`; a pack may override via `pack.policies`. Add `policies` to `ActionPack` (frozen dataclass, `field(default_factory=dict)`); validate in `__post_init__` that policy keys are in `fields`. Run `.venv/bin/pip install langgraph` and add to `requirements.txt`.

- [ ] **Step 4: Run tests** -> all pass; also run `.venv/bin/python -m pytest tests/evaluation -v` to confirm existing tests still pass.

### Task 2: Evidence, prompts, parsing (pure functions)

**Files:**
- Create: `src/evaluation/extract/evidence.py`, `src/evaluation/extract/prompts.py`
- Test: `tests/evaluation/extract/test_evidence_prompts.py`

**Interfaces:**
- Produces (`evidence.py`): `rules_lines(pack, rep, field, excerpts) -> list[str]`, `rules_raw_values(pack, rep, field, excerpts) -> list[str]`, `gliner_lines(pack, spans, field) -> list[str]`, `cue_score(window, cues) -> int`. These are verbatim moves of `_rules_lines`, `_rules_raw_values`, `_gliner_lines`, `_cue_score` (including the `MAX_*` constants and the `find_settlement` import).
- Produces (`prompts.py`): `select_prompt(pack, field, evidence: str, *, mode: Literal["copy","pick"]) -> str`, `validate_prompt(pack, field, value, evidence) -> str`, `parse_field(raw: str, field: str) -> str | None`, `parse_keep(raw: str) -> bool | None`. Verbatim moves; `select_prompt` takes `mode` instead of sniffing the `"EXCERPT:\n"` prefix (copy mode formats `pack.clause_fields[field].extract_prompt`).

- [ ] **Step 1: Write failing characterization tests** with hand-built fixtures (`rep` with two rules facts, `spans` with one allowed and one disallowed hint, a settlement excerpt): exact expected line strings including `hint=... value='...' context='...'` and the `MAX_GLINER=25` cap. Parsing tests: plain JSON, ```json fenced, `<think>..</think>` prefix, `"N/A"` -> None, field missing but `"value"` key present, garbage -> None, `parse_keep` garbage -> None, `{"keep": false}` -> False. Prompt tests: empty evidence (`"(no "` prefix) yields the "return null" prompt; copy mode substitutes `{excerpt}`.
- [ ] **Step 2: Run** -> FAIL.
- [ ] **Step 3: Move the functions** from the script (copy, do not delete yet; the script is switched in Task 6). Remove the leading underscores.
- [ ] **Step 4: Run** -> pass.

### Task 2b: Pack hooks for pack-specific evidence logic

Added after the harness gained merger-only branches (re-read the current `scripts/eval_unified_field_qwen.py`: `primary_entity` prior, acquirer-drop vs primary entity, junk role names, `A_inventory` direct pass, cash-only "No stock consideration" synthesis). These must become pack config, not graph/harness code.

**Files:**
- Modify: `src/evaluation/action_packs/base.py` (add `PackHooks` dataclass and `ActionPack.hooks: PackHooks | None = None`), `src/evaluation/action_packs/merger.py` (supply hooks with the current merger behaviour), `src/evaluation/extract/evidence.py` (`gliner_lines` and a new `build_rules_prelude` consume hooks), `src/evaluation/extract/policies.py` (derive an inventory-prior stage)
- Test: `tests/evaluation/extract/test_hooks.py`

**Interfaces:**
- Produces (`base.py`): `PackHooks(junk_roles: frozenset[str] = frozenset(), drop_span: Callable[[str, str, Mapping[str, str]], bool] | None = None, rules_prelude: Callable[[str, Mapping[str, str]], list[str]] | None = None, direct_prior: Callable[[str, Mapping[str, str]], str | None] | None = None, synth_spans: Callable[[str, list[str], list[dict], Mapping[str, str]], list[str]] | None = None, prior_label: str = "A_inventory")`. The `Mapping[str, str]` argument is `EventContext.extras` (event-level strings the provider supplies, e.g. `primary_entity`). `drop_span(field, raw, extras) -> bool` returns True to drop a span. `synth_spans(field, gliner_lines, spans, extras)` returns extra evidence lines when the normal span lines are empty.
- Produces (`evidence.py`): `gliner_lines(pack, spans, field, *, extras: Mapping[str, str] | None = None) -> list[str]` applying `pack.hooks` (`junk_roles`, `drop_span`) in place of the hard-coded checks; `rules_prelude_lines(pack, field, extras) -> list[str]`; `synth_lines(pack, field, gliner: list[str], spans, extras) -> list[str]`.
- Produces (`policies.py`): `resolve_policy(..., cascade=True)` prepends a `Stage(name="prior", sources=("prior",), on_empty="skip", direct_from_rules=True, direct_label=hooks.prior_label, ...)` only when `pack.hooks.direct_prior` returns a value is checked at run time by the executor; the policy adds the stage for every field when `pack.hooks and pack.hooks.direct_prior` is set (the executor skips it when `direct_prior(field, extras)` is None, using `on_empty="skip"`).
- Merger hooks reproduce the current script exactly: `junk_roles = {"parent","merger sub","merger subsidiary","company","purchaser"}`; `drop_span` drops a span for field `acquirer` when its text is the same org as `extras["primary_entity"]` (reuse `norm_org`/`same_org` from `evidence.py`); `rules_prelude` prepends `- hint=primary_entity method=inventory value='<entity>'` for field `target`; `direct_prior` returns the primary entity for field `target` (pass label `A_inventory`); `synth_spans` returns the `No stock consideration` evidence block for field `stock_exchange_ratio` when no ratio spans exist but `cash_consideration` spans do. The default junk set of `gliner_lines` becomes empty (only a pack's `junk_roles` apply); the generic names `parent`, `company`, `purchaser` move into merger's `junk_roles` too (as listed).
- No `merger` string may appear in `src/evaluation/extract/`; the hooks and their merger text live in `merger.py`.

- [ ] **Step 1: Write failing tests** in `test_hooks.py`: `test_junk_roles_come_only_from_pack_hooks`; `test_drop_span_called_with_extras`; `test_rules_prelude_prepended_for_target_only`; `test_synth_spans_only_when_no_ratio_spans`; `test_pack_without_hooks_behaves_as_before` (gliner lines identical to a pack with `hooks=None`); `test_resolve_policy_adds_prior_stage_only_with_direct_prior_hook`; plus a merger-pack test for each of the four behaviours using hand-built `spans` and `extras={"primary_entity": "Acme Corp"}` (acquirer span "Acme Corporation" dropped, "Parent" dropped, target gets the prelude line).
- [ ] **Step 2: Run** -> FAIL.
- [ ] **Step 3: Implement** as above; update Task 2's `evidence.py` accordingly (remove its `extra_junk`/`_JUNK_ROLE_NAMES` stopgap).
- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/evaluation/extract -v` -> pass.

### Task 3: Providers, nodes, graph

**Files:**
- Create: `src/evaluation/extract/providers.py`, `src/evaluation/extract/temporal.py`, `src/evaluation/extract/nodes/{__init__,retrieve,prompt,llm,normalize,validate}.py`, `src/evaluation/extract/graph.py`
- Test: `tests/evaluation/extract/test_graph.py`

**Interfaces:**
- Produces (`providers.py`):
  - `class EvidenceProvider(Protocol)`: `context(self, req: FieldExtractRequest) -> EventContext`; `bundle(self, ctx: EventContext, field: str, sources: tuple[str, ...], pack: ActionPack) -> EvidenceBundle`; `rules_direct(self, ctx, field, pack) -> list[str]`; `n_rules(self, ctx, field, pack) -> int`.
  - `EventContext`: frozen dataclass holding `rep, spans, excerpts, passages, doc_text, temporal_cache`.
  - `ArtifactProvider(pack, store: ArtifactStore, tagger, rows_by_accession)`: reads preprocess artifacts. Move `_load_rep`, `_load_spans`, `_passages_obj`, `_spans_from_passages`, `_excerpts_from_passages`, `_segment_blob`, `_excerpts` from the script and reproduce the artifact-fallback logic from the script's `prepared` loop (GT passages fill missing spans/excerpts; merger event id is `merger_{accession}`; tender uses `gt_event_ids_from_corpus`). Add `prepare(rows, fields)` that precomputes contexts (and temporal) once per event; `context()` is a cache lookup keyed by accession and raises `KeyError` for unprepared events.
  - `temporal.py`: lazy `importlib` load of `scripts/eval_temporal_tagger_dates.py` plus `precompute_temporal` and `temporal_lines` (moved from the script, with the `_TAGGER_LOCK`).
- Produces (`graph.py`): `build_extract_graph(pack, backend, provider) -> CompiledGraph`; `run_field(graph, req: FieldExtractRequest) -> FieldExtractResult`. `run_field` catches any exception and returns `pass_used="error"`, `pred=None`, `raw_llm=str(e)[:400]`.
- Graph state is a Pydantic model: request, policy, stage index, last bundle, `pred`, `pass_used`, `raw_log`, `evidence_final`, result. Nodes: `retrieve` (build the bundle for the current stage, applying `on_empty`), `prompt`, `llm` (call `backend.chat_json`, `parse_field`), `advance` (conditional edge: stage finished with a pred -> `normalize`; else next stage or `normalize`), `normalize` (`pack.normalize`), `validate` (only if the producing stage has `validate`, `req.validate_enabled`, and pred is not None).

Parity rules to reproduce (read `extract_field` in the script; the tests below pin them): clause with empty retrieve returns `pass_used="clause_miss"` with no LLM call; cascade Pass A with no rules does nothing and leaves `pass_used="none"`; a direct-rules hit uses no LLM call and `pass_used="A_rules"`; cascade ends `"empty"` only if no stage set a label and Pass B evidence was empty; oneshot with empty evidence still asks the LLM; the temporal source yields nothing unless `pack.uses_temporal(field)`; the validate drop appends `+C_drop`, keep appends `+C_keep`, unparseable keep leaves the label unchanged.

- [ ] **Step 1: Write failing tests** in `test_graph.py` with a `FakeBackend` (scripted replies keyed by call order, records prompts) and a `FakeProvider` (dict-backed): `test_clause_miss_no_llm_call`, `test_clause_hit_uses_copy_prompt_and_normalizes`, `test_direct_rules_field_skips_llm`, `test_cascade_falls_from_A_to_B_labels` (A null -> `pass_used == "B"`; B null -> `"B_null"`), `test_cascade_no_rules_no_evidence_is_empty`, `test_oneshot_empty_evidence_still_calls_llm`, `test_validate_drop_sets_pred_none_and_label`, `test_non_date_field_never_requests_temporal`, `test_backend_exception_returns_error_result`, `test_missing_artifacts_returns_null_no_raise` (provider with empty context), `test_concurrent_invocations_isolated` (16 fields via `ThreadPoolExecutor(4)`, each gets its own result), and `test_malformed_llm_output_is_null`.
- [ ] **Step 2: Run** -> FAIL.
- [ ] **Step 3: Implement** the providers, nodes and graph. Backend and provider are closed over at build time; nothing event-specific appears in node code.
- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/evaluation/extract -v` -> pass.

### Task 4: Parity gate against the legacy `extract_field`

**Files:**
- Create: `tests/evaluation/extract/test_parity_legacy.py`
- Create: `tests/evaluation/extract/fakes.py` (shared `FakeBackend`; add `EchoFirstBackend`)

**Interfaces:**
- Consumes: `build_extract_graph`, `run_field`, `ArtifactProvider`, and the still-present legacy `extract_field` (import the script via `importlib`; `pytest.importorskip("transformers")` if the temporal import needs it).
- `EchoFirstBackend.chat_json(system, user, model)`: deterministic. Returns `{"<field>": <first value=/date= string found in the evidence>}` or null, `{"keep": true}` for validate prompts. This removes LLM nondeterminism so only control flow is compared.

- [ ] **Step 1: Write the test.** For tender and merger packs, over every holdout event that has preprocess artifacts (skip if none), over all `core` fields, in the three modes (cascade, oneshot via `cascade=False`, with and without validate), assert that `(pred, pass_used, n_evidence_chars, n_rules)` from the legacy function equals `FieldExtractResult` from the graph for each `(event, field)`. Temporal is disabled (`tagger=None`) so the test is hermetic and fast. Add the same assertion over a synthetic fixture that exercises clause hit and clause miss so the test is meaningful when real artifacts are absent.
- [ ] **Step 2: Run:** `.venv/bin/python -m pytest tests/evaluation/extract/test_parity_legacy.py -v`. Expected: pass. Any mismatch is a graph or policy bug; fix it there, not in the test.

### Task 5: Prove a new action is config-only

**Files:**
- Create: `tests/evaluation/extract/test_new_pack.py`

- [ ] **Step 1: Write the test.** Define an inline `ActionPack` named `"rights_test"` (two fields, one clause field with its own patterns and prompt, one date field) with no `policies`. Run it through `build_extract_graph` with a fake provider and `FakeBackend`. Assert the correct policy resolves, the clause field extracts from a regex hit, the other field cascades, and no file under `src/evaluation/extract/` changed (the point is that the test needs no code beyond the pack). Also assert `grep -rniE "tender|merger|proration|SC TO" src/evaluation/extract` finds nothing (implement as a Python scan of the package source, excluding docstring-free matches of the words in `tests`).
- [ ] **Step 2: Run** -> pass. If the scan finds strings, remove them from the package.

### Task 6: Switch the harness to the graph

**Files:**
- Modify: `scripts/eval_unified_field_qwen.py` (delete the moved helpers and `extract_field`; the loop builds `FieldExtractRequest` and calls `run_field`; temporal tagger loading and `ensure_holdout`/scoring stay)
- Test: `tests/evaluation/extract/test_harness_cli.py`

**Interfaces:**
- Consumes: Tasks 1 to 3. The script keeps the exact `details`/summary JSON keys it writes today (`accession`, `event_id`, `n_spans`, `n_excerpt_chars`, per-field `pred/pass_used/...`, `pass_counts`, baselines).
- `n_spans` / `n_excerpt_chars` now come from `EventContext`.

- [ ] **Step 1: Write a test** that runs `main()` with a stub backend (monkeypatch `make_backend`) and `--limit 2 --no-temporal` against a tmp `--out`, and asserts the summary JSON keys and that every `(event, field)` has a `pass_used` string. Skip if holdout artifacts are absent.
- [ ] **Step 2: Run** -> FAIL (pre-change keys come from old path or import breakage).
- [ ] **Step 3: Rewire the script.** Keep `ThreadPoolExecutor` concurrency; each job calls `run_field(graph, req)`; remove `try/except` there since `run_field` returns the error result.
- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/evaluation -v` -> pass. Task 4's parity test now needs the legacy function: before deleting it, copy it to `tests/evaluation/extract/legacy_extract.py` (frozen reference) and point Task 4 at that file; rerun Task 4 to confirm it still passes.
- [ ] **Step 5: Manual live check** (needs the Orin hub): `.venv/bin/python scripts/eval_unified_field_qwen.py --pack tender --backend orin --model gemma4:26b --split holdout --no-cascade --limit 20 --run-name graph_replay_limit20`. Compare per-field and micro F1 with `outputs/tender_eval/experiments/runs/verify_c4_reasoning_none_limit20/` (about 0.64 micro). Report the numbers; differences beyond LLM noise (more than about 0.02 micro) mean a parity gap to investigate.

### Task 7: Docs

**Files:**
- Modify: `docs/action-pack-unified-extract.md` (rewrite §5 as as-built: layout, DTOs, `FieldPolicy`/`Stage`, how to add a pack; update §2 pointers), `docs/superpowers/specs/2026-11-13-extract-graph-dto-design.md` (record the two deviations: `Stage` list instead of flat `FieldPolicy` fields, and a single `clause` source backed by `retrieve_clause` instead of separate `quotes`/`regex`)

- [ ] **Step 1: Update both docs.** Include a short "add a new corporate action" checklist: write `src/evaluation/action_packs/<name>.py`, register in `get_pack`, optionally set `policies`, run the harness with `--pack <name>`.
- [ ] **Step 2: Verify** every file path mentioned in the docs exists (`ls`).
