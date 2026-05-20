# IPS Design Notes

> 2026-05-21 — grill-with-docs session output. Subject to refinement.

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

`D:\agents\` — self-contained. CTW reference files (taxonomy/types.yaml, infolevel/LEVELS.md, llmwiki/SCHEMA.md, templates) are **copied into** `D:\agents\templates/`, not referenced in-place. This makes the agent stable and snapshot-able, independent of CTW spec changes.

```
D:\agents\
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

## MVP scope (v0)

1. Telegram bot receives a URL
2. Agent fetches content, auto-detects type, proposes Assessment
3. User approves → Agent ingests, generates source-summary + ZK candidates
4. User approves candidates → Agent writes permanent notes to `D:\agents\zettelkasten/2-permanent/`
5. `/status` and `/history` Telegram commands work
6. Basic dashboard shows: current run + recent runs + file changes

Deferred to post-MVP: multi-URL orchestration, Reports, workflow insights, failure self-resolution, folder drop support.

## Unresolved

- Web dashboard tech stack (framework, server)
- Input source type auto-detection rules
- Processing Plan / Assessment template structure
- How CTW reference files (taxonomy/types.yaml, infolevel templates) are loaded — copied into D:\agents or referenced in-place from contextToWhatend
