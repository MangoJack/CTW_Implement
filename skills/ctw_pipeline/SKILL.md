---
name: ctw_pipeline
description: CTW 主控管线 — 分类→路由→摄入 全流程编排
version: "1.0"
---

# CTW Pipeline

CTW (Context To Workflow) 主控管线编排器。

串联三个 CTW 技能完成完整的信息处理流程：
`ctw_classify` → `ctw_infolevel` → `ctw_ingest`

## 触发

当用户提供信息源并需要完整的 CTW 处理时触发。

## 流程

```
SourceInput
    │
    ▼
┌─────────────┐
│  CLASSIFY   │ ← TaxonomyClassifier (ctw_classify)
│  内容类型分类 │    10 种内容类型 + 置信度
│  Gate: ✓    │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  ROUTE      │ ← InfoLevelRouter (ctw_infolevel)
│  深度路由    │    L0-L4 + 推荐模板路径
│  Gate: ✓    │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  INGEST     │ ← LLMWikiIngest (ctw_ingest)
│  LLM Wiki   │    摘要→实体→概念→对比→ZK候选
│  摄入       │
│  Gate: ⏸    │ ← APPROVE_OUTPUT (pending_modified)
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  ZK         │
│  候选笔记    │
│  Gate: ⏸    │ ← APPROVE_ZK (pending_modified)
└──────┬──────┘
       │
       ▼
PipelineResult
  ├── classify: ClassifyResult
  ├── level: LevelResult
  ├── ingest: IngestResult
  ├── zk_notes: list[ZkCandidate]
  ├── gates_triggered: list[GateTrigger]
  ├── output_files: list[str]
  └── status: init | processing | waiting_human | complete | error
```

## 使用

```python
from ctw_pipeline import CTWPipeline, run_pipeline
from ctw_types import SourceInput

# 方式 1: 类实例
pipeline = CTWPipeline()
source = SourceInput(
    url="https://github.com/user/repo",
    title="My Tool",
    content="## Overview\n...",
)
result = pipeline.run(source)

# 方式 2: 便利函数
result = run_pipeline({
    "url": "https://example.com",
    "title": "Example Source",
    "content": "...",
})

# 方式 3: 跳过阶段（用于测试或手动控制）
result = pipeline.run(
    source,
    classify_override=ClassifyResult(content_type=ContentType.TOOL_EXTENSION),
    level_override=LevelResult(level=InfoLevel.L2),
)

print(result.status)          # "complete" or "waiting_human"
print(len(result.zk_notes))   # 提取的 ZK 候选数
print(result.gates_triggered) # 触发的 gates
```

## 依赖

- `skills/ctw_classify/` — 内容类型分类
- `skills/ctw_infolevel/` — 深度等级路由
- `skills/ctw_ingest/` — LLM Wiki 摄入
- `lib/` — 共享类型和配置

## Gates

| Gate | Stage | Status | Human Action |
|------|-------|--------|--------------|
| CLASSIFY | classify | passed | 自动通过 |
| APPROVE_OUTPUT | ingest | pending_modified | 审核 ingest 产出 |
| APPROVE_ZK | zk | pending_modified | 审核 ZK 候选 |
| PROMOTE | promote | deferred | 升级到永久笔记 |
