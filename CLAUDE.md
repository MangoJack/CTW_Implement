# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CTW (Context To Workflow) Implement is a Python pipeline that processes information sources through three stages: **Classify** (10 content types) → **Route** (L0-L4 depth levels) → **Ingest** (generate LLM Wiki markdown + Zettelkasten candidates). It is the pipeline core extracted from the larger `contextToWhatend` project.

## Commands

```bash
# Run all tests (101 tests, ~1.2s)
python -m pytest skills/ tests/ -v

# Run a single module's tests
python -m pytest skills/ctw_classify/tests/ -v
python -m pytest skills/ctw_infolevel/tests/ -v
python -m pytest skills/ctw_ingest/tests/ -v
python -m pytest skills/ctw_pipeline/tests/ -v
python -m pytest tests/test_lib.py -v
```

Only dependency: `pyyaml`. Python >= 3.10.

## Architecture

```
SourceInput → [Classify] → ClassifyResult → [Route] → LevelResult → [Ingest] → IngestResult + ZkCandidate[]
```

**lib/** — shared dataclasses/enums (`ctw_types.py`) and config loader (`ctw_config.py`). All types in `ctw_types.py` mirror the upstream `contextToWhatend/taxonomy/types.yaml`. `ctw_config.py` loads YAML config from the upstream project via `CTWConfig`, which resolves paths via: env var `CTW_PROJECT_PATH` → constructor arg → hardcoded default.

**skills/ctw_classify/** — Stage 1. `DecisionTree` (keyword matching with word-boundary regex for ASCII, substring for CJK) runs first. Confidence < 0.8 triggers `TaxonomyClassifier.classify_with_llm()`, which is currently a stub (no real LLM call). Uses a "highest confidence wins" strategy across all 10 types with order breaking ties.

**skills/ctw_infolevel/** — Stage 2. `InfoLevelRouter` maps content type → default depth (L0-L4), with per-type max level bounds. Supports manual override with `can_upgrade()` bounds checking.

**skills/ctw_ingest/** — Stage 3. `LLMWikiIngest` generates source summary, entity pages, concept pages, comparison pages, and ZK candidates based on content type routing rules. Templates are inlined (not loaded from upstream `llmwiki/templates/`). Output paths are built relative to the configured repository path.

**skills/ctw_pipeline/** — Orchestrator. `CTWPipeline.run()` chains all three stages and records Gate triggers (CLASSIFY, APPROVE_OUTPUT, APPROVE_ZK). `run_pipeline()` is a convenience function accepting a dict.

## Import System

The project has no `setup.py` or `pyproject.toml`. All modules use `sys.path.insert()` to find `lib/` and sibling skill directories. The root is at `D:\MainWorkSpace\CTW_Implement`. When writing code that imports from `lib/` or other skills, follow the same `sys.path.insert()` pattern used in existing modules.

## Upstream Dependency

This project reads taxonomy configuration from `contextToWhatend/taxonomy/types.yaml` at `D:\MainWorkSpace\contextToWhatend`. The `CTWConfig` constructor accepts a `ctw_project_path` override. The upstream project defines 10 content types with keywords, value questions, default info levels, and output targets.

## Known Limitations

- LLM classification is a stub — `classify_with_llm()` still uses the decision tree result with a slight confidence bump, no API calls
- Gate states are recorded but don't actually block/pause for human interaction
- Templates are inlined in `ingest.py` rather than loaded from upstream `llmwiki/templates/`
- No package management — `sys.path.insert()` everywhere; `pip install -e .` not available
- `ctw_templates.py` and `ctw_output.py` in lib/ are stubs (reserved for future implementation)
- Decision tree keywords are hardcoded in `decision_tree.py`, not loaded from types.yaml
- Value questions are loaded from types.yaml but never used in the ingest stage
