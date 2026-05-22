# IPS Design Notes

> 2026-05-21 — grill-with-docs session output. Updated 2026-05-22 with v2.1 status.
>
> **Implementation status**: All MVP items implemented. 238 tests passing. LLM integration (DeepSeek) live. State persistence active. Pattern analysis + adaptive learning functional. First production run completed (Bilibili BV1xjLt6FE7d) with Hermes supervision.

## Resolved design decisions

### System boundary

Covers the bottom 4 layers of CTW: **Taxonomy → InfoLevel → LLM Wiki → Zettelkasten**. Harness/CyberRole/CyberEmployee are out of scope for now.

Outputs: Permanent notes + on-demand Reports (persistent, iteratively refined).

### Input sources

- **URL** — most common. System auto-detects content type (article, video, GitHub repo, etc.)
- **Folder drop** — pre-processed summaries + raw media from other agents

### Interaction model

OpenClaw-based independent agent with its own workspace, exposed via **Telegram chat**.

Three feedback channels:
1. **Real-time processing progress** — status updates as the system ingests/classifies/generates
2. **State visibility** — Telegram commands (`/status`, `/history`, `/run <id>`) + web dashboard browsing
3. **Workflow adaptation** — system records deviations and periodically suggests plan refinements

### Processing flow (two-phase)

```
Phase 1: Assessment
  1. User pastes URL/folder → Agent acknowledges receipt
  2. Agent classifies (Taxonomy type + InfoLevel depth) → presents Assessment (high-level goals + direction)
  3. User confirms direction or redirects

Phase 2: Execution Steps
  4. Agent presents concrete Processing Plan steps
  5. User confirms or overrides (Workflow Deviation recorded)
  6. Agent runs Ingest with real-time progress updates
  7. Agent presents results → source summary, entities, concepts, atomization candidates
  8. User approves Zettelkasten candidates → Agent writes permanent notes
  9. On request → Agent generates Reports (iterative, versioned)
```

### Multi-URL orchestration

When multiple URLs arrive together, the agent proposes an **Orchestration Plan** — which inputs share stages, which conflict, what runs parallel vs. sequential. Orchestration strategy is recorded for later optimization. (Post-MVP.)

### Human-in-the-loop learning

System records **Workflow Deviations** (human overrides). Periodically analyzes patterns and suggests refinements, e.g.:

> "GitHub repos with >500 stars — you've overridden L1 to L3 7/10 times. Should I default to L3?"

Human always makes the final choice. System recommends only. (Post-MVP.)

### Reports

- Persistent files under `reports/`
- Iterative refinement via **Report Chains** (v1 → v2 → synthesis)
- Each report is an Output Artifact traceable to its Processing Run
- (Post-MVP.)

### Zettelkasten format

Follows CTW spec: `YYYYMMDDHHmmss ID`, YAML frontmatter, `[[wikilinks]]`, stored in `zettelkasten/2-permanent/`.

### Monitoring

- **Telegram commands**: `/status`, `/history`, `/run <id>`
- **Web dashboard**: Lightweight custom page with live push (SSE/WebSocket), shows current run progress, recent runs, queue, file changes, and workflow insights

### Error handling

Immediate notification → system tries self-resolution (multiple approaches, restrained — no infinite retry) → if all fail, notify again and wait for human.

### Workspace

**Code repo**: `https://github.com/MangoJack/CTW_Implement.git` — clone to any local path. Root auto-detected from `__file__`.

**Agent workspace**: `~/agents/ips-agent/` (default, cross-platform) or set `CTW_PROJECT_PATH` env var. CTW reference files (taxonomy/types.yaml, infolevel/LEVELS.md, llmwiki/SCHEMA.md, templates) are **copied into** `<workspace>/templates/`, not referenced in-place. This makes the agent stable and snapshot-able, independent of CTW spec changes.

**Artifact repository**: `\\MilesFNas\personal_folder\ctw\ctw0520\` — where pipeline output files (wiki pages, ZK notes) are written. Configured via `CTW_REPO_PATH` env var or `config/settings.yaml`.

```
~/agents/ips-agent/
├── raw/                      ← ingested source files
├── wiki/                     ← LLM Wiki compiled pages
│   ├── sources/
│   ├── entities/
│   ├── concepts/
│   └── comparisons/
├── zettelkasten/
│   └── 2-permanent/          ← atomic permanent notes
├── reports/                  ← on-demand Report Chains
├── state/                    ← status files (dashboard reads these + agent pushes updates)
│   ├── queue.json
│   ├── runs/
│   └── index.json
├── templates/                ← CTW reference files (copied) + Processing Plan templates
├── CONTEXT.md
└── config.md
```

### Pipeline stages

The processing pipeline has four discrete stages:

```
[Fetch] → [Classify] → [Route] → [Ingest]
```

- **Fetch** (`ctw_fetch`): HTTP GET / API calls to retrieve remote content. Auto-detects source type from URL domain. Produces a populated `SourceInput`.
- **Classify** (`ctw_classify`): Decision tree + LLM fallback to determine content type (10 types). Produces `ClassifyResult` with confidence, value questions, output targets.
- **Route** (`ctw_infolevel`): Maps content type → InfoLevel depth (L0-L4). Supports manual override with per-type max bounds. Produces `LevelResult`.
- **Ingest** (`ctw_ingest`): Generates LLM Wiki pages (source-summary, entity, concept, comparison) and ZK candidates. Writes to artifact repository. Produces `IngestResult`.

### Entry point

The `/ctw_analysis` Telegram command is implemented by `ctw_analyzer`. It orchestrates the two-phase interaction model (Assessment → human confirm → Execution Steps → human confirm → run pipeline). The analyzer does NOT bypass the pipeline — it wraps it with the two-phase protocol.

### Assessment / Execution Steps template structure

**Assessment** (Phase 1 — presented to human for direction confirmation):

```
📋 Assessment — <title-or-url>

Content type: <type-name> (confidence: XX%)
Recommended depth: LX — <level-name>
Source type: <article/repo/video/pdf/tool/model>

What this is: <one-paragraph summary of what the system thinks this input is>

Direction: <recommended approach — go deep / quick scan / skip>
Why: <one-sentence reasoning>

Key questions this input raises:
  • <value question 1>
  • <value question 2>

❓ Confirm direction or suggest changes.
```

**Execution Steps** (Phase 2 — presented after Assessment is confirmed):

```
📝 Processing Plan — <title>

Steps:
  1. Fetch content from <url> (<fetch strategy>)
  2. Classify → <type-name> (decision tree + LLM)
  3. Route to depth <LX> — <level-name>
  4. Ingest → generate:
     • Source summary page
     • <N> entity page(s)
     • <N> concept page(s)
     • <N> comparison page(s)
     • ~<N> ZK candidates

Expected outputs: <N> files to wiki/ + zettelkasten/

Any deviations from defaults: <none / list of overrides>
Workflow Deviation recorded: <yes if human changed type/depth/scope>

❓ Approve plan or suggest changes.
```

## MVP scope (v0)

1. Telegram bot receives a URL
2. Agent fetches content, auto-detects type, proposes Assessment
3. User approves → Agent ingests, generates source-summary + ZK candidates
4. User approves candidates → Agent writes permanent notes to `D:\agents\zettelkasten/2-permanent/`
5. `/status` and `/history` Telegram commands work
6. Basic dashboard shows: current run + recent runs + file changes

Deferred to post-MVP: multi-URL orchestration, Reports, workflow insights, failure self-resolution, folder drop support.

## Unresolved

- Web dashboard tech stack (framework, server) — post-MVP
