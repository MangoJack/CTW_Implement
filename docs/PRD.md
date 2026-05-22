## Problem Statement

The CTW Implement pipeline processes information sources through classify → route → ingest, but lacked several capabilities that make it a genuinely intelligent, adaptive system:

1. **LLM integration** — classification and content generation were stubs; the system couldn't make real semantic decisions or produce meaningful analysis
2. **No persistence** — state lived only in memory; restarting the process lost all history
3. **No learning** — Workflow Deviations were recorded but never analyzed; the system never adapted to user behavior
4. **No observability** — no way to see usage patterns, trends, or system health over time

## Solution

Extend the CTW pipeline with three interconnected capabilities:

1. **Real LLM integration** — wire DeepSeek API (via OpenClaw config auto-discovery) into classification fallback and content generation. Decision tree runs first; LLM re-classifies when confidence < 0.8. Ingest uses LLM to generate source summaries, entity pages, and comparison pages with template fallback on failure.

2. **State persistence** — add a JSON Lines store (`state/runs/YYYY-MM.jsonl`) that persists every pipeline run's full result. Each run is one line, appended atomically, with an in-memory index for fast run_id lookup. This is the data foundation for all analysis.

3. **Pattern analysis + adaptive learning** — analyze historical Workflow Deviations to detect user preferences. When the user consistently (≥2 times) corrects the same type or depth for the same domain/content-type, the system auto-applies that correction in future runs. Single-occurrence patterns are surfaced as suggestions. A trend report provides periodic observability.

These three capabilities form a feedback loop: runs persist → patterns are analyzed → future runs adapt → more runs persist.

## User Stories

### LLM integration
1. As a knowledge worker, I want the system to use real LLM semantic classification when keyword confidence is low, so that ambiguous content gets a reasonable type assignment.
2. As a knowledge worker, I want LLM-generated source summaries with core arguments, abstracts, and key concepts, so that wiki pages contain meaningful analysis rather than template stubs.
3. As a knowledge worker, I want LLM-generated entity pages with overview, core capabilities, technical architecture, and usage scenarios, so that tool/agent evaluations are substantive.
4. As a knowledge worker, I want the system to fall back to template rendering when the LLM is unavailable, so that processing never blocks on API issues.
5. As a system operator, I want CTW to auto-discover LLM configuration from OpenClaw's config files, so that I don't need to configure API keys in two places.

### State persistence
6. As a knowledge worker, I want every processing run automatically persisted to disk, so that my history survives process restarts.
7. As a knowledge worker, I want runs organized by month in human-readable JSON Lines files, so that I can inspect or query my history with standard tools.
8. As a knowledge worker, I want to look up a specific run by its run_id, so that I can retrieve details of a past processing session.
9. As a knowledge worker, I want historical data to be the foundation for pattern analysis, so that the system learns from my actual behavior over time.

### Adaptive learning — type correction
10. As a knowledge worker, I want the system to notice when I repeatedly correct the same content type for the same domain, so that it auto-applies my preference in future runs.
11. As a knowledge worker, I want auto-applied corrections recorded as Workflow Deviations with `source: "learned"`, so that I can distinguish system-learned changes from my manual overrides.
12. As a knowledge worker, I want single-occurrence corrections surfaced as suggestions rather than auto-applied, so that I'm not locked into one-off decisions.

### Adaptive learning — depth preference
13. As a knowledge worker, I want the system to notice when I consistently prefer deeper or shallower analysis for a content type, so that it adjusts the default depth automatically.
14. As a knowledge worker, I want inconsistent depth preferences (sometimes up, sometimes down) to not trigger auto-application, so that the system doesn't overfit to noise.
15. As a knowledge worker, I want learned preferences to only apply when I haven't already manually overridden in the current run, so that my explicit instructions always take priority.

### Trend reports
16. As a knowledge worker, I want to generate a trend report showing type distribution, depth distribution, and cancellation rate over a time window, so that I understand my content consumption patterns.
17. As a knowledge worker, I want the trend report to include average classification confidence and deviation rate, so that I can monitor system health.
18. As a knowledge worker, I want the trend report to surface my top domains and content types, so that I can see where my attention is going.

### Threshold and confidence
19. As a knowledge worker, I want the auto-apply threshold to be 2 same-direction deviations, so that a single override is treated as advisory while a pattern triggers automatic adjustment.
20. As a knowledge worker, I want learned corrections to have no expiration, so that even old patterns remain effective until I establish new ones.

## Implementation Decisions

### Architecture

**LLM integration:**
- `ctw_llm` module reads OpenClaw config chain: `openclaw.json` → `models.json` → `auth-profiles.json`
- Direct API calls to DeepSeek (OpenAI-compatible), not proxied through OpenClaw runtime
- Model ID case normalization: OpenClaw stores `deepseek-v4-Pro` but API expects `deepseek-v4-pro`
- Reasoning model fallback: when `content` is empty, extract from `reasoning_content` field
- Default model: `deepseek-chat` (stable, non-reasoning)
- classifier.classify_with_llm() builds a prompt listing all 10 content types, parses LLM response for type + confidence + reason
- ingest methods (generate_source_summary, generate_entity_page, generate_comparison_pages) call LLM with structured prompts; fall back to template rendering on failure

**State persistence:**
- `RunStore` class in a shared library module
- JSON Lines format, one line per run, appended atomically
- Files partitioned by month: `state/runs/YYYY-MM.jsonl`
- In-memory index (`state/index.json`) maps run_id → (file, byte_offset) for O(1) lookup
- `_make_serializable()` helper recursively converts dataclasses, Paths, and Enums to JSON-safe types
- Persistence failure is non-fatal — wraps in try/except, never blocks pipeline execution
- `state/` directory is gitignored

**Pattern analysis:**
- `PatternAnalyzer` class with three analysis modes, all reading from RunStore
- Type corrections: group deviations by (domain, original_type → new_type), count occurrences
- Depth preferences: group deviations by (content_type, direction_up/down), count occurrences
- Trend reports: aggregate over time window — status distribution, type/depth counts, confidence avg, deviation rate, top domains
- Hybrid application mode:
  - ≥2 same-direction deviations → auto-apply with `source: "learned"`
  - 1 deviation → surface as suggestion only
  - Inconsistent directions → neither auto-applied
- `get_suggestions(url, content_type, depth)` is the single entry point called by plan()
- Auto-application only fires when human has not already manually overridden in the current run

**Schema change:**
- WorkflowDeviation gains a `source` field: `"human"` (manual override) or `"learned"` (auto-applied pattern)

**plan() integration:**
- After parsing human feedback, before building execution steps: query pattern suggestions
- Auto-apply: modify assessment dict, append learned WorkflowDeviation entries
- Suggestions: include non-auto-applied hints in the plan response's `suggestions` field
- Pattern analysis failures are caught and silently skipped (advisory, never blocking)

**execute() integration:**
- After run completes (success, cancellation, or error): save full result to RunStore
- Result dict includes top-level convenience fields: `url`, `timestamp`, `content_type`, `confidence`, `recommended_depth`, `deviations`, `files_written`
- Save failure is caught and ignored

### No new dependencies
All new modules use stdlib only (`json`, `os`, `pathlib`, `urllib.parse`, `collections`). The project maintains its single-dependency principle (`pyyaml` only).

## Testing Decisions

### What makes a good test
Tests verify external behavior through public interfaces. For persistence: save → load → assert data round-trips. For pattern analysis: populate store with known deviations → query suggestions → assert auto-apply thresholds and suggestion content. No tests for internal serialization helpers or file layout; those are implementation details.

### New test modules
| Module | Tests | Focus |
|--------|-------|-------|
| ctw_state (RunStore) | 14 | Save/load round-trip, since filter, limit, deviation filtering, run_id lookup, month partitioning, Unicode preservation, dataclass serialization |
| patterns (PatternAnalyzer) | 14 | Type correction counting + auto-apply threshold, depth preference direction + auto-apply threshold, trend report aggregation, learned deviation source field |
| Integration | 1 | WorkflowDeviation accepts `source="learned"` |
| **Total new** | **33** | |

Total test count: 205 → 238.

### Prior art
All new tests follow existing project patterns: pytest with fixtures, one test class per concern, descriptive method names. The RunStore tests use `tempfile.TemporaryDirectory` for isolation (same pattern as existing config tests). The pattern analysis tests use a `_mk_store` helper that pre-populates a RunStore with known data (same pattern as existing fixture-based tests in ctw_classify).

## Out of Scope

- Web dashboard (framework, server, SSE/WebSocket)
- Multi-URL orchestration plans (parallel/sequential execution)
- Folder drop support (pre-processed summaries from other agents)
- Gate blocking/pausing mechanism — gates are recorded but don't pause for human interaction
- Async execution — all processing is synchronous
- Package management standardization (setup.py / pyproject.toml)
- Time-windowed pattern expiration — all historical deviations are permanently weighted equally
- LLM result caching for tests — real API calls mean classify/ingest/pipeline tests take ~7min total

## Further Notes

The system now implements a closed feedback loop: every run is persisted → historical deviations are analyzed → patterns inform future runs → future runs are persisted. The threshold of 2 same-direction deviations for auto-application balances responsiveness (learns quickly) with stability (doesn't overfit to one-offs).

The `state/` directory is the single source of truth for all runtime history. It can be backed up, queried with `jq`, or analyzed with external tools — the JSON Lines format is deliberately tool-agnostic.

Current status: 238 tests passing. LLM integration (DeepSeek API) is live. Persistence writes on every execute(). Pattern analysis fires on every plan() when human hasn't manually overridden. Trend reports are available via `PatternAnalyzer.generate_trend_report(days=N)`.
