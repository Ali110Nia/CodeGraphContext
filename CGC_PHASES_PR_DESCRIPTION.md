# feat: Add embedding pipeline (Phase 4) and inheritance-aware re-resolution (Phase 5)

## Summary

This PR adds two new post-indexing resolution phases that significantly improve CALLS edge quality in Java codebases, and fixes a critical import bug that prevented Phases 4 and 5 from ever running.

---

## Critical Bug Fix

**`pipeline.py`**: Four-dot relative import (`from ....cli.config_manager`) went above the top-level package boundary, crashing every `cgc index` run with `"attempted relative import beyond top-level package"` before Phase 4 could execute. Fixed to `from ...cli.config_manager`.

---

## New Files

### `src/codegraphcontext/tools/indexing/embeddings.py` (266 lines)
Generates semantic embeddings for all `Function` nodes and writes them back to Neo4j.

- Uses `fastembed` with `BAAI/bge-small-en-v1.5` (384-dim ONNX, Python 3.13 compatible, no torch dependency)
- Falls back gracefully to `sentence-transformers` if fastembed is unavailable
- Paths filtered using `STARTS WITH` (not `CONTAINS`) for cross-repo safety
- Handles anonymous functions with a `"(anonymous)"` fallback to prevent blank embeddings from crashing the model
- Streams in batches of 256, writes back to Neo4j atomically per batch

### `src/codegraphcontext/tools/indexing/vector_resolver.py` (137 lines)
ANN vector similarity search used as tiebreaker in Phase 5.

- Queries Neo4j vector index for top-K similar functions by name
- Dynamic `effective_top_k = max(self.top_k, len(candidate_paths))` — previously hardcoded `top_k=5` silently missed correct candidates when >5 existed
- Returns ranked candidate paths for caller to score

### `src/codegraphcontext/tools/indexing/resolution/post_resolution.py` (205 lines)
Phase 5: Re-resolves tier-7/8 CALLS edges (same-file fallbacks) using the `INHERITS` graph and optional vector similarity.

**Algorithm:**
1. Find all same-file CALLS edges involving classes that participate in inheritance
2. Look up all known implementations of the called method name across the class hierarchy
3. Score candidates: interface matches > concrete implementation matches
4. If `VectorResolver` is available and scores are tied, use embedding similarity as tiebreaker
5. MERGE improved edges at tier-10 (inheritance-resolved) or tier-11 (vector-resolved)

**Implementation fixes vs naive approach:**
- Step 2 uses a single `UNWIND` batch query for all unique method names (was N separate queries — critical for large repos like nucleus with 258K functions)
- Null guard on `called_name`: external `Module` refs have null `called.name`, which was propagating into Cypher
- `line_number` removed from MERGE key (null caused unpredictable duplicate edge creation); moved to `SET ... coalesce(...)` after MERGE
- MATCH clause uses WHERE for null-safe caller line check

---

## Modified Files

### `src/codegraphcontext/tools/indexing/pipeline.py`
- Fixed `....cli` → `...cli` (4 dots → 3) — the root cause of Phase 4+5 never running
- Added Phase 4 block (embedding generation, `ENABLE_VECTOR_RESOLVE` gated)
- Added Phase 5 block (inheritance re-resolution, `ENABLE_INHERIT_RESOLVE` gated)
- Both phases wrapped in `try/except` — failures log a warning but do NOT mark the job FAILED

### `src/codegraphcontext/core/watcher.py`
- Consolidated duplicate `_gcv` (config value getter) imports in Steps 8 and 9 into a single guarded block
- Step 9 now instantiates `VectorResolver` when `ENABLE_VECTOR_RESOLVE=true` — previously it was always `None`, so tier-11 edges never fired for incremental file-change events
- Both steps gated by `_vector_enabled` / `_inherit_enabled` booleans from a single config read

### `src/codegraphcontext/tools/indexing/resolution/calls.py`
- Java `package_name` extraction from `package` directive (fixes 0% → 93% package coverage)
- Qualified name (`qualified_name`) construction for Function nodes
- Improved cross-file resolution for DI field/variable receivers

### `src/codegraphcontext/tools/indexing/persistence/writer.py`
- Writes `package_name` and `qualified_name` to File/Function nodes respectively

---

## New Test Files

- `tests/unit/tools/test_calls_resolution_tiers.py` (323 lines) — resolution tier ordering, tier-10/11 edge creation
- `tests/unit/tools/test_embeddings_and_vector_resolver.py` (328 lines) — EmbeddingPipeline, VectorResolver, dynamic top_k
- `tests/unit/parsers/test_java_package_qualified_names.py` (260 lines) — package_name and qualified_name extraction

---

## Configuration Flags

Add to `~/.codegraphcontext/.env`:
```
ENABLE_INHERIT_RESOLVE=true   # Enable Phase 5 (inheritance re-resolution). Default: false
ENABLE_VECTOR_RESOLVE=true    # Enable Phase 4 (embeddings) + tier-11 tiebreaker. Default: false
```

Phase 5 runs in all cases when `ENABLE_INHERIT_RESOLVE=true`. Vector similarity tiebreaker in Phase 5 only activates when both flags are true.

---

## Test Results

```
239 passed, 2 skipped, 0 failed
```

---

## Benchmark Results (Nexus, 5,941 files / 52,719 functions)

| Metric | Before | After |
|---|---|---|
| Total CALLS edges | 70,537 | 186,981 (+165%) |
| Cross-file CALLS | 49% | 70% |
| Tier-7 fallbacks | 34,371 (49%) | 31,690 (16%) |
| `execute` same-file | 100% | 8% ✅ |
| `execute` distinct targets | 43 (14%) | 99 (33%) |
| Functions embedded | 0 | 52,719 (100%) |
| Tier-10 edges (inherit) | 0 | 144 |
| Tier-11 edges (vector) | 0 | 248 |
| `package_name` set | 0% | 93% |
| `qualified_name` set | 0% | 96% |

The remaining 31,690 tier-7 fallbacks are Spring XML-wired beans — unsolvable via AST alone, require XML config parsing (proposed Phase 6).
