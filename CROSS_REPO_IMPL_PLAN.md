# Cross-Repo Resolution — Implementation Plan

> **Status:** Verified against `cgc-latest` source on 2026-04-27. Updated from
> a draft authored by a smaller model: corrected the universality claim,
> tightened the resolution Cypher to be repo-scoped, added a config gate
> consistent with existing Phase 4/5, fixed the watcher integration point,
> and added a generalization track for non-Java languages.

---

## Problem

When nexus imports `com.ea.nucleus.billing.invoice.Invoice`, the graph stores
a `Module` node with `full_import_name = "com.ea.nucleus.billing.invoice.Invoice"`.
The actual class definition lives in the nucleus repo as a `Class` node with
`qualified_name = "com.ea.nucleus.billing.invoice.Invoice"`. **No edge connects
the two**, so cross-repo call/dependency queries are impossible today.

## Goal

Add a **config-driven, per-repo, language-agnostic-by-design** cross-repo
linking phase that:

1. Reads `<repo>/.codegraphcontext/cgc_repo_config.json` for declared targets.
2. For each `cross_repo` target, resolves `Module → Class` across repos by
   joining `Module.full_import_name` to the callee class's FQN.
3. Writes idempotent `RESOLVES_TO` edges with provenance (`from_repo`,
   `to_repo`, `linked_at`).
4. Runs automatically as **Phase 6** of `cgc index`, on watcher file events,
   and via a manual `cgc cross-link run` command.
5. Is gated by `ENABLE_CROSS_REPO_LINK` env-var, mirroring the existing
   Phase 4 (`ENABLE_VECTOR_RESOLVE`) and Phase 5 (`ENABLE_INHERIT_RESOLVE`)
   flags.

---

## Value Unlocked

The single edge `(Module)-[:RESOLVES_TO]->(Class)` is small but enables
several capabilities that are currently impossible:

| Capability | Today | After |
|---|---|---|
| **Impact analysis across repos** — "if I change `Invoice.java` in nucleus, what breaks in nexus?" | Manual grep across both repos | One Cypher query traversing `RESOLVES_TO` |
| **True dependency map** — which nucleus packages does nexus actually consume (vs. which are merely declared in `pom.xml`)? | POM-only view, no usage signal | Per-class usage counts grouped by package |
| **Caller graphs that cross repo boundaries** — find every nexus function that flows through a specific nucleus type | Only same-repo CALLS edges | Combine `IMPORTS → RESOLVES_TO` with `CALLS` |
| **Dead code detection at the org level** — nucleus classes nobody imports | Can only find unused-within-nucleus | Find `Class` nodes with zero inbound `RESOLVES_TO` from any consumer repo |
| **Migration / refactor planning** — moving a package from `com.ea.nucleus.x` to `com.ea.nucleus.y` | Unknown blast radius | Concrete file-level list of consumer changes needed |
| **AI agent context** — Copilot answering "how is `Invoice` used in nexus" | Returns guesses or only nucleus self-uses | Returns precise nexus call sites |

Plus second-order benefits:

- The same `RESOLVES_TO` mechanism scales to **N>2 repos** (nexus, nucleus,
  nova-utilities, …) — no code change, just an extra entry in the config file.
- Provenance metadata (`from_repo`, `to_repo`, `linked_at`) makes it trivial
  to detect stale links after a repo is renamed or deleted, and to audit
  which links were created when.

---

## Is This Java-Specific?

**The transport is universal; the join key is currently Java-only.**

- `Module.full_import_name` is populated by **every language parser**
  (java, python, csharp, cpp, kotlin, scala, ruby, perl, php, rust, swift,
  dart, c, elixir, haskell). So the *importer* side of the join works for
  every language out of the box.
- `Class.qualified_name` is currently set **only** by the Java parser
  ([`java.py:297`](src/codegraphcontext/tools/languages/java.py#L297)).
  Other language parsers emit Class nodes with `name` and `path` but no FQN.

This means **Phase 6 ships working for Java first**, and the same
`run_cross_repo_link()` function generalizes to other languages by adding
`qualified_name` population to their parsers (see "Generalization" below).
The Phase 6 code itself does **not** need any language-specific branches.

---

## Config Format

Each repo that depends on another declares it in its own
`.codegraphcontext/cgc_repo_config.json`:

```json
{
  "cross_repo": [
    {
      "to": "/Users/kbhaskarla/Documents/workspace/nucleus",
      "description": "nucleus identity, billing and platform services"
    },
    {
      "to": "/Users/kbhaskarla/Documents/workspace/nova-utilities",
      "description": "shared platform utilities"
    }
  ]
}
```

Only the `to` path is needed — the `from` repo is the one that owns the file.
The description is optional but useful for `cgc cross-link list`.

This file is **not** in `.gitignore` — it is intentional per-repo metadata
that should be committed alongside the code, like `.nvmrc` or
`pyrightconfig.json`.

---

## Schema Change

No new node properties or constraints are needed. Add one composite index
to `schema.py` for query performance:

```cypher
CREATE INDEX resolves_to_repos IF NOT EXISTS
FOR ()-[r:RESOLVES_TO]-()
ON (r.from_repo, r.to_repo)
```

`RESOLVES_TO` edge properties:

| Property    | Type   | Description                                     |
|-------------|--------|-------------------------------------------------|
| `from_repo` | string | Absolute path of the importing (caller) repo    |
| `to_repo`   | string | Absolute path of the exporting (callee) repo    |
| `linked_at` | string | ISO-8601 timestamp; refreshed on every re-link  |

> Neo4j 5+ syntax. The existing `schema.py` already uses the same
> `CREATE INDEX … IF NOT EXISTS FOR ()-[r:…]-()` form for relationship
> indexes, so no compatibility work is needed.

---

## Files to Create

### 1. `src/codegraphcontext/core/repo_config.py` (NEW)

Reads/writes `<repo>/.codegraphcontext/cgc_repo_config.json`.

```python
def load_repo_config(repo_path: Path) -> dict
    """Returns parsed JSON or {} if file not found."""

def get_cross_repo_targets(repo_path: Path) -> list[dict]
    """Returns list of {'to': str, 'description': str} dicts."""

def add_cross_repo_target(repo_path: Path, to_path: str, description: str = "") -> None
    """Appends a new target, creating the config file if needed.
    No-op (with warning) if the same `to` already exists."""

def remove_cross_repo_target(repo_path: Path, to_path: str) -> bool
    """Removes target by path. Returns True if found and removed."""
```

### 2. `src/codegraphcontext/tools/indexing/resolution/cross_repo_resolution.py` (NEW)

Core resolution pass — mirrors `post_resolution.py` structure (info_logger
prefix, batch sizing, single try/except guard at the call site).

```python
def run_cross_repo_link(
    driver: Any,
    from_repo_path: str,
    to_repo_paths: list[str],
) -> int:
    """
    Resolve Module nodes imported by `from_repo` to Class nodes in any of
    `to_repo_paths` by matching full_import_name == qualified_name.

    Returns count of RESOLVES_TO edges created or refreshed.
    """
```

**Algorithm — two-step, repo-scoped to avoid noisy edges:**

```cypher
-- Step 1: collect candidate FQNs imported FROM the source repo only.
-- (Module nodes are global; we must filter by the IMPORTS edge's File path.)
MATCH (f:File)-[:IMPORTS]->(m:Module)
WHERE f.path STARTS WITH $from_prefix
  AND m.full_import_name IS NOT NULL
RETURN DISTINCT m.full_import_name AS fqn
```

```cypher
-- Step 2: for each target repo, MERGE edges in batches.
-- The repo-prefix guard on BOTH sides is what prevents spurious links
-- when multiple repos define classes with the same FQN.
UNWIND $fqns AS fqn
MATCH (m:Module {full_import_name: fqn})<-[:IMPORTS]-(f:File)
WHERE f.path STARTS WITH $from_prefix
MATCH (c:Class {qualified_name: fqn})
WHERE c.path STARTS WITH $to_prefix
MERGE (m)-[r:RESOLVES_TO]->(c)
ON CREATE SET r.from_repo = $from_repo,
              r.to_repo   = $to_repo,
              r.linked_at = $now
ON MATCH  SET r.linked_at = $now
RETURN count(r) AS linked
```

Notes:

- `from_prefix` and `to_prefix` are normalized with a trailing `/` (same
  pattern as `post_resolution.py:54`) so that `/repos/nexus` does not
  accidentally match `/repos/nexus_extra`.
- FQN list is chunked at `_FQNS_BATCH = 500` to stay under Neo4j parameter
  limits (mirrors `_NAMES_BATCH` in `post_resolution.py:88`).
- `ON MATCH SET r.linked_at = $now` lets operators detect stale links by
  comparing `linked_at` to the most recent indexing run.

---

## Files to Modify

### 3. `src/codegraphcontext/tools/indexing/schema.py`

Add the composite index alongside the existing `CREATE INDEX` block.

### 4. `src/codegraphcontext/tools/indexing/pipeline.py`

After the existing Phase 5 `if (_gcv("ENABLE_INHERIT_RESOLVE") …)` block
(currently ending at line 115), add Phase 6 with the **same gating pattern**:

```python
# ── Phase 6: cross-repo linking (optional, config-gated) ──────────────────
if (_gcv("ENABLE_CROSS_REPO_LINK") or "false").lower() == "true":
    try:
        from ...core.repo_config import get_cross_repo_targets
        from .resolution.cross_repo_resolution import run_cross_repo_link
        targets = get_cross_repo_targets(path)
        if targets:
            to_paths = [t["to"] for t in targets]
            n_linked = run_cross_repo_link(writer.driver, str(path.resolve()), to_paths)
            info_logger(f"[CROSS-REPO] Linked {n_linked} Module→Class edges across {len(to_paths)} target repo(s)")
        else:
            info_logger("[CROSS-REPO] No cross_repo targets declared; skipping.")
    except Exception as _ce:
        info_logger(f"[CROSS-REPO] Phase skipped: {_ce}")
```

### 5. `src/codegraphcontext/core/watcher.py`

After the existing `if _inherit_enabled:` block (~line 218, **not** line 201),
add a parallel `if _cross_repo_enabled:` block. Read the flag in the same
upfront `_gcv` block where `_vector_enabled` and `_inherit_enabled` are read
(~line 184), so all three phase flags are loaded once per file event.

```python
# Add to the up-front config read block (~line 183–187):
_cross_repo_enabled = (_gcv("ENABLE_CROSS_REPO_LINK") or "false").lower() == "true"

# After the _inherit_enabled block:
if _cross_repo_enabled:
    try:
        from codegraphcontext.core.repo_config import get_cross_repo_targets
        from codegraphcontext.tools.indexing.resolution.cross_repo_resolution import run_cross_repo_link
        targets = get_cross_repo_targets(self.repo_path)
        if targets:
            to_paths = [t["to"] for t in targets]
            n = run_cross_repo_link(self.graph_builder.driver, str(self.repo_path), to_paths)
            info_logger(f"[CROSS-REPO] Incremental: {n} edges (re)linked")
    except Exception as _e:
        warning_logger(f"[CROSS-REPO] Incremental failed: {_e}")
```

### 6. `src/codegraphcontext/cli/main.py`

Add a new `cross_link_app` Typer group, following the existing `mcp_app`,
`neo4j_app`, `context_app` pattern:

```
cgc cross-link add    <from-repo> <to-repo> [--description "..."]
cgc cross-link remove <from-repo> <to-repo>
cgc cross-link list   <repo>
cgc cross-link run    <repo>          # trigger Phase 6 manually, no re-index
```

Example session:

```bash
# Declare nexus depends on nucleus
cgc cross-link add /workspace/nexus /workspace/nucleus \
  --description "nucleus identity and billing services"

# Run the linking pass now (without re-indexing)
ENABLE_CROSS_REPO_LINK=true cgc cross-link run /workspace/nexus

# See what's declared
cgc cross-link list /workspace/nexus

# Query in Neo4j after linking
# MATCH (f:File)-[:IMPORTS]->(m:Module)-[:RESOLVES_TO]->(c:Class)
# WHERE f.path CONTAINS '/nexus/' RETURN f.path, c.qualified_name LIMIT 20
```

> `cgc cross-link run` should bypass the env-var gate (the user has
> explicitly requested the operation) but should still log a warning if the
> gate is off, since `cgc index` and the watcher would otherwise skip it.

---

## Phase Ordering Summary

| Phase | Name                     | File                            | Trigger           | Gate flag                  |
|-------|--------------------------|---------------------------------|-------------------|----------------------------|
| 1–3   | Parse + Write            | `pipeline.py`                   | `cgc index`       | always-on                  |
| 4     | Embeddings               | `embeddings.py`                 | `cgc index`, watcher | `ENABLE_VECTOR_RESOLVE`    |
| 5     | Inheritance Re-resolve   | `post_resolution.py`            | `cgc index`, watcher | `ENABLE_INHERIT_RESOLVE`   |
| **6** | **Cross-Repo Linking**   | **`cross_repo_resolution.py`**  | **`cgc index`, watcher, `cgc cross-link run`** | **`ENABLE_CROSS_REPO_LINK`** |

---

## Query Examples (after implementation)

```cypher
-- All nexus files that use a nucleus class
MATCH (f:File)-[:IMPORTS]->(m:Module)-[:RESOLVES_TO]->(c:Class)
WHERE f.path CONTAINS '/nexus/'
RETURN f.path, c.qualified_name, c.path

-- Impact analysis: what breaks in nexus if Invoice changes?
MATCH (c:Class {qualified_name: 'com.ea.nucleus.billing.invoice.Invoice'})
      <-[:RESOLVES_TO]-(m:Module)<-[:IMPORTS]-(f:File)
WHERE f.path CONTAINS '/nexus/'
RETURN f.path

-- Function-level: which nexus functions sit in files that import a nucleus type?
MATCH (fn:Function)<-[:CONTAINS]-(f:File)-[:IMPORTS]->(m:Module)-[:RESOLVES_TO]->(c:Class)
WHERE f.path CONTAINS '/nexus/'
RETURN fn.name, fn.path, c.qualified_name

-- Dependency heat map: which nucleus packages does nexus depend on the most?
MATCH (f:File)-[:IMPORTS]->(m:Module)-[:RESOLVES_TO]->(c:Class)
WHERE f.path CONTAINS '/nexus/' AND c.path CONTAINS '/nucleus/'
WITH split(c.qualified_name, '.')[0..4] AS pkg
RETURN pkg, count(*) AS usages ORDER BY usages DESC

-- Stale-link audit: edges not refreshed in the last 24h
MATCH ()-[r:RESOLVES_TO]->() WHERE r.linked_at < $cutoff_iso
RETURN r.from_repo, r.to_repo, count(r) AS stale
```

---

## Acceptance Criteria

1. `cgc index /path/to/nexus` with `ENABLE_CROSS_REPO_LINK=true` and
   `cgc_repo_config.json` declaring nucleus completes Phase 6 and logs
   `[CROSS-REPO] Linked N Module→Class edges`.
2. The query `MATCH (m:Module)-[:RESOLVES_TO]->(c:Class) RETURN count(*)`
   returns N > 0 in Neo4j.
3. Re-running `cgc index` does **not** create duplicate edges (MERGE
   idempotency) and refreshes `linked_at` on existing edges.
4. Touching a single `.java` file under `/nexus/` triggers the watcher's
   incremental Phase 6 within the debounce window and refreshes only the
   affected edges' `linked_at`.
5. With `ENABLE_CROSS_REPO_LINK=false` (or unset), Phase 6 is a no-op and
   logs nothing — same behavior as Phase 4/5 today.
6. A repo with no `cgc_repo_config.json` (or with an empty `cross_repo`
   array) skips Phase 6 with an informational log message and zero edges.

---

## Generalization to Other Languages

The Phase 6 code is language-agnostic. To extend coverage beyond Java, only
the parsers need to populate `qualified_name` on Class nodes. There is **no
change to `cross_repo_resolution.py` or schema** for any of the steps below.

| Language | FQN derivation | Effort |
|---|---|---|
| **Python** | `package_path_from_file(path) + "." + class_name`, where `package_path_from_file` walks up the directory tree until it leaves a directory containing `__init__.py`. | ~30 LOC in `python.py` |
| **C#** | Concatenate enclosing `namespace_declaration` text with class `name`. The `csharp.py` parser already captures `(qualified_name) @name` for namespaces. | ~20 LOC in `csharp.py` |
| **Kotlin** | Package declaration + class name (mirror of Java). | ~15 LOC in `kotlin.py` |
| **Scala** | Package declaration + class/object name. | ~15 LOC in `scala.py` |
| **Go** | Package path (from `go.mod` resolution) + identifier. Requires resolving module root first. | Moderate — needs `go.mod` lookup |
| **TypeScript / JavaScript** | Imports are **path-based, not FQN-based** (`import { Foo } from "./bar"`). Cross-repo linking for TS/JS requires a different join: resolve relative paths to absolute file paths and match `File` nodes directly. **Track as a separate Phase 6b.** | Different design needed |

Recommended rollout:

1. Phase 6 (this plan) — ships Java-only working end-to-end.
2. Follow-up MR — populate `qualified_name` for Python and C# parsers; no
   Phase 6 changes needed, the same `RESOLVES_TO` edges start appearing
   automatically once parsers re-index.
3. Phase 6b (separate plan) — path-based resolution for TS/JS imports.

---

## Out of Scope

- Wildcard / star import resolution (`com.ea.nucleus.*` → all classes in
  package). Java-static imports of fields/methods. Both can be handled by
  later passes that consult `Module.alias` and package-level lookups.
- Cross-repo `CALLS` and `INHERITS` edges. With `RESOLVES_TO` in place,
  these can be synthesized in a later phase by composing
  `CALLS-target-name` + `RESOLVES_TO` + `Class CONTAINS Function`.
- Path-based (TS/JS) cross-repo resolution — see Phase 6b above.
- Auto-discovery of `to` repos from build files (`pom.xml` `<dependency>`,
  `package.json` workspaces). The config file is intentionally explicit so
  the operator controls which repos participate.
# Cross-Repo Resolution — Implementation Plan

## Problem

When nexus imports `com.ea.nucleus.billing.invoice.Invoice`, the graph records
a `Module` node with `full_import_name = "com.ea.nucleus.billing.invoice.Invoice"`.
The actual class definition lives in the nucleus repo as a `Class` node with
`qualified_name = "com.ea.nucleus.billing.invoice.Invoice"`. There is currently
no edge connecting them, so cross-repo call/dependency queries are impossible.

## Goal

Add a config-driven, per-repo cross-repo linking phase that:
1. Reads a `cgc_repo_config.json` file from `<repo>/.codegraphcontext/`
2. For each declared `cross_repo` pair, resolves `Module → Class` across repos
3. Writes `RESOLVES_TO` edges in Neo4j with provenance metadata
4. Runs automatically after indexing and on watcher file-change events
5. Is idempotent (safe to re-run; uses MERGE)

---

## Config Format

Each repo that depends on another declares it in its own
`.codegraphcontext/cgc_repo_config.json`:

```json
{
  "cross_repo": [
    {
      "to": "/Users/kbhaskarla/Documents/workspace/nucleus",
      "description": "nucleus identity, billing and platform services"
    },
    {
      "to": "/Users/kbhaskarla/Documents/workspace/nova-utilities",
      "description": "shared platform utilities"
    }
  ]
}
```

> Only the `to` path is needed — the `from` repo is the one that owns the file.
> The description is optional but useful for `cgc cross-link list`.

This file is **not** in `.gitignore` — it's intentional per-repo metadata that
should be committed alongside the code (like a `.nvmrc` or `pyrightconfig.json`).

---

## Schema Change

Add one new relationship type to `schema.py`:

```cypher
-- No new constraint needed; Module already has UNIQUE on name.
-- RESOLVES_TO edges are created via MERGE so duplicates never form.
-- Add a composite index for query performance:

CREATE INDEX resolves_to_repos IF NOT EXISTS
FOR ()-[r:RESOLVES_TO]-()
ON (r.from_repo, r.to_repo)
```

`RESOLVES_TO` edge properties:

| Property    | Type   | Description                                     |
|-------------|--------|-------------------------------------------------|
| `from_repo` | string | Absolute path of the importing (caller) repo    |
| `to_repo`   | string | Absolute path of the exporting (callee) repo    |
| `linked_at` | string | ISO-8601 timestamp of when the edge was created |

---

## Files to Create

### 1. `src/codegraphcontext/core/repo_config.py` (NEW)

Reads/writes `<repo>/.codegraphcontext/cgc_repo_config.json`.

```python
def load_repo_config(repo_path: Path) -> dict
    """Returns parsed JSON or {} if file not found."""

def get_cross_repo_targets(repo_path: Path) -> list[dict]
    """Returns list of {'to': str, 'description': str} dicts."""

def add_cross_repo_target(repo_path: Path, to_path: str, description: str = "") -> None
    """Appends a new target to cgc_repo_config.json, creating it if needed."""

def remove_cross_repo_target(repo_path: Path, to_path: str) -> bool
    """Removes target by path. Returns True if found and removed."""
```

### 2. `src/codegraphcontext/tools/indexing/resolution/cross_repo_resolution.py` (NEW)

Core resolution pass — mirrors `post_resolution.py` structure.

```python
def run_cross_repo_link(
    driver: Any,
    from_repo_path: str,
    to_repo_paths: list[str],
) -> int:
    """
    Resolve Module nodes in from_repo to Class nodes in to_repos
    by matching full_import_name == qualified_name.

    Returns count of RESOLVES_TO edges created or already existing.

    Algorithm:
      1. MATCH (f:File)-[:IMPORTS]->(m:Module)
             WHERE f.path STARTS WITH $from_prefix
               AND m.full_import_name IS NOT NULL
         RETURN DISTINCT m.name, m.full_import_name

      2. For each to_repo:
         MATCH (c:Class)
             WHERE c.path STARTS WITH $to_prefix
               AND c.qualified_name IN $fqns
         RETURN c.qualified_name, elementId(c)

      3. Batch MERGE:
         UNWIND $pairs AS pair
         MATCH (m:Module {full_import_name: pair.fqn})
         MATCH (c:Class {qualified_name: pair.fqn})
               WHERE c.path STARTS WITH pair.to_prefix
         MERGE (m)-[r:RESOLVES_TO]->(c)
         ON CREATE SET r.from_repo = pair.from_repo,
                       r.to_repo   = pair.to_repo,
                       r.linked_at = pair.linked_at
         RETURN count(r) as linked
    """
```

---

## Files to Modify

### 3. `src/codegraphcontext/tools/indexing/schema.py`

Add after the existing `CREATE INDEX` statements:

```python
session.run(
    "CREATE INDEX resolves_to_repos IF NOT EXISTS "
    "FOR ()-[r:RESOLVES_TO]-() ON (r.from_repo, r.to_repo)"
)
```

### 4. `src/codegraphcontext/tools/indexing/pipeline.py`

After the existing `run_inheritance_reresolve` call block (currently Phase 5),
add Phase 6 — cross-repo linking:

```python
# Phase 6: cross-repo resolution
try:
    from ...core.repo_config import get_cross_repo_targets
    from .resolution.cross_repo_resolution import run_cross_repo_link
    targets = get_cross_repo_targets(Path(repo_path_str))
    if targets:
        to_paths = [t["to"] for t in targets]
        n_linked = run_cross_repo_link(writer.driver, repo_path_str, to_paths)
        info_logger(f"[CROSS-REPO] Linked {n_linked} Module→Class edges")
except Exception as _e:
    warning_logger(f"[CROSS-REPO] Phase skipped: {_e}")
```

### 5. `src/codegraphcontext/core/watcher.py`

After the existing Phase 5 block (around line 201), add a parallel block
for Phase 6 using the same guard pattern (`try/except` with `warning_logger`).

### 6. `src/codegraphcontext/cli/main.py`

Add a new `cross_link_app` Typer command group under `cgc cross-link`:

```
cgc cross-link add    <from-repo> <to-repo> [--description "..."]
cgc cross-link remove <from-repo> <to-repo>
cgc cross-link list   <repo>
cgc cross-link run    <repo>          # trigger resolution pass manually
```

Example CLI interactions:

```bash
# Declare nexus depends on nucleus
cgc cross-link add /workspace/nexus /workspace/nucleus \
  --description "nucleus identity and billing services"

# Run the linking pass now (without re-indexing)
cgc cross-link run /workspace/nexus

# See what's declared
cgc cross-link list /workspace/nexus

# Query in Neo4j after linking
# MATCH (f:File)-[:IMPORTS]->(m:Module)-[:RESOLVES_TO]->(c:Class)
# WHERE f.path CONTAINS '/nexus/'
# RETURN f.path, c.qualified_name, c.path
# LIMIT 20
```

---

## Phase Ordering Summary

| Phase | Name                     | File                            | Trigger         |
|-------|--------------------------|---------------------------------|-----------------|
| 1–3   | Parse + Write            | `pipeline.py`                   | `cgc index`     |
| 4     | Embeddings               | `embeddings.py`                 | `cgc index`     |
| 5     | Inheritance Re-resolve   | `post_resolution.py`            | `cgc index`     |
| **6** | **Cross-Repo Linking**   | **`cross_repo_resolution.py`**  | **`cgc index`, watcher, `cgc cross-link run`** |

---

## Query Examples (after implementation)

```cypher
-- All nexus files that use a nucleus class
MATCH (f:File)-[:IMPORTS]->(m:Module)-[:RESOLVES_TO]->(c:Class)
WHERE f.path CONTAINS '/nexus/'
RETURN f.path, c.qualified_name, c.path

-- Impact analysis: what breaks in nexus if Invoice changes?
MATCH (m:Module {full_import_name: 'com.ea.nucleus.billing.invoice.Invoice'})
      <-[:IMPORTS]-(f:File)
WHERE f.path CONTAINS '/nexus/'
RETURN f.path

-- Function-level: which nexus functions call through a nucleus type?
MATCH (fn:Function)-[:CALLS]->(callee),
      (f:File)-[:CONTAINS]->(fn),
      (f)-[:IMPORTS]->(m:Module)-[:RESOLVES_TO]->(c:Class)
WHERE f.path CONTAINS '/nexus/'
RETURN fn.name, fn.path, c.qualified_name

-- Dependency map: all nucleus packages nexus depends on
MATCH (f:File)-[:IMPORTS]->(m:Module)-[:RESOLVES_TO]->(c:Class)
WHERE f.path CONTAINS '/nexus/'
      AND c.path CONTAINS '/nucleus/'
WITH split(c.qualified_name, '.')[0..4] as pkg
RETURN pkg, count(*) as usages ORDER BY usages DESC
```

---

## Out of Scope (not in this plan)

- Wildcard import resolution (`com.ea.nucleus.*` → multiple classes) — future work
- Cross-repo CALLS edges (function A in nexus calls function B in nucleus directly)
- Cross-repo INHERITS edges
- Non-Java repos (this plan is Java/Maven-specific; Python/TS can follow the same
  pattern using `qualified_name` once those parsers emit it)
