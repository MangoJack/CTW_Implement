# IPS — Information Processing System

An OpenClaw-based agent that ingests URLs and folders, classifies content via CTW's Taxonomy+InfoLevel, processes it through the LLM Wiki pipeline, and produces Zettelkasten permanent notes and on-demand reports. Interaction happens through Telegram chat with human-in-the-loop approval at every processing stage.

## Language

### Core objects

**Input Source** (输入源):
A URL or folder dropped into the system for processing. URLs auto-detect the content type (article, video, repo, etc.). Folders contain pre-processed summaries and raw media from other agents.
_Avoid_: Submission, entry, item, resource

**Processing Plan** (处理计划):
A two-phase proposal the agent presents before executing. Phase 1 is a high-level **Assessment** (整体评价与目标) — what the input is, the recommended approach, and the goals. Once the human confirms the direction, Phase 2 presents the concrete **Execution Steps**. Always approved before execution begins. For complex tasks, the overview gives the human a chance to redirect before details are worked out.
_Avoid_: Workflow, pipeline step list, task list

**Assessment** (总体评价):
The Phase 1 overview of a Processing Plan. Contains a brief classification, goal summary, and recommended direction — enough for the human to judge "is this the right approach?" before detailed steps are presented.
_Avoid_: Summary, abstract, preview

**Processing Run** (处理运行):
A single execution of a Processing Plan against one Input Source. Has a lifecycle: proposed → approved → in-progress → complete. All outputs trace back to their Processing Run.
_Avoid_: Session, job, task, execution

**Workflow Deviation** (流程偏离):
A human override of the proposed Processing Plan — changing the classification, adding steps, skipping steps, or inserting new requirements. The deviation reason is recorded and periodically analyzed to suggest plan refinements.
_Avoid_: Exception, override (too generic), change request

### Outputs

**Permanent Note** (永久笔记):
An atomic Zettelkasten note stored in `zettelkasten/2-permanent/`. Format: `YYYYMMDDHHmmss` ID, YAML frontmatter, `[[wikilinks]]`. One idea per note. Created from LLM Wiki's atomization candidate list after human approval.
_Avoid_: Zettel, card, entry, snippet

**Report** (报告):
A persistent, iteratively-refined document generated from conversational requests. Reports are versioned and form chains (e.g., report v1 → v2 → synthesis). Stored in a `reports/` workspace directory.
_Avoid_: Summary, output, digest

**Report Chain** (报告链):
A sequence of Reports that refine and synthesize the same subject. Earlier reports feed into later ones. The final report in the chain supersedes but references its predecessors.
_Avoid_: Report series, report history

**Orchestration Plan** (编排计划):
When multiple Input Sources arrive together, the agent proposes a coordinated Processing Plan that considers synergies (shared stages, related topics), conflicts (shared resources), and ordering (dependencies). Parallel and sequential segments are decided per-batch. The orchestration strategy is recorded for later optimization.
_Avoid_: Batch plan, queue strategy

### Context (inherited from CTW)

**Taxonomy**:
The 10-type content classification system from CTW's `taxonomy/types.yaml`. Answers "what type of information is this?"

**InfoLevel**:
The 5-level processing depth classification from CTW's `infolevel/LEVELS.md` (L0–L4). Answers "how deep should we process this?"

**LLM Wiki**:
The single knowledge entry point — raw sources ingested, compiled into structured wiki pages (entities, concepts, comparisons, source summaries). Produces atomization candidate lists for Zettelkasten.

## Flagged ambiguities

_None yet._

## Example dialogue

> **Dev**: When the user pastes a GitHub URL and the system proposes L1 Tool Review but the user says "this repo is huge, go deeper" — what gets recorded?

> **Domain expert**: A Workflow Deviation. The Processing Plan had `InfoLevel: L1`, the human overrode to `InfoLevel: L3`. The deviation record includes the reason ("repo exceeded expected complexity") and the final plan. Later, the system might suggest: "GitHub repos with >500 stars — you've overridden L1 to L3 7 out of 10 times. Should I default to L3 for repos above that threshold?"

> **Dev**: And the output — if the repo generates a report chain?

> **Domain expert**: Right — the Processing Run for that Input Source could produce a `reports/some-repo-v1.md`, the human asks follow-up questions, and that triggers a second Processing Run resulting in `reports/some-repo-v2.md`. Both are linked in a Report Chain with the final synthesis at the end. Each Report is an Output Artifact of its own Processing Run.
