---
name: ctw_ingest
description: CTW LLM Wiki 摄入 — 从分类+路由后的源生成摘要/实体/概念/对比/ZK候选
version: "1.0"
---

# CTW Ingest

CTW (Context To Workflow) 管线第三阶段：LLM Wiki 摄入。

将已分类并完成深度路由的信息源，通过 LLM 管道生成结构化知识产物。

## 触发

在 ctw_classify 和 ctw_infolevel 完成后触发，对信息源进行深度摄入。

## 产出

根据内容类型和深度等级，生成不同组合的产出：

| 内容类型 | 源摘要 | 实体页 | 概念页 | 对比页 | ZK候选 |
|---------|:---:|:---:|:---:|:---:|:---:|
| tool-extension | ✓ | ✓ | - | ✓ | ✓ |
| tool-review | ✓ | ✓ | - | ✓ | ✓ |
| practice-tutorial | ✓ | - | - | - | ✓ |
| architecture-analysis | ✓ | ✓ | ✓ | ✓ | ✓ |
| paper-review | ✓ | - | ✓ | - | ✓ |
| tech-news | ✓ | - | - | - | ✓ |
| experience-share | ✓ | - | - | - | ✓ |
| spec-standard | ✓ | - | - | - | ✓ |
| security-research | ✓ | ✓ | - | ✓ | ✓ |
| ai-agent | ✓ | ✓ | - | ✓ | ✓ |

## 流程

```
SourceInput + ClassifyResult + LevelResult
    │
    ▼
┌─────────────────────────────────────┐
│           LLMWikiIngest             │
│                                     │
│  ✓ generate_source_summary()        │
│  ✓ generate_entity_page()  (按需)   │
│  ✓ generate_concept_pages() (按需)  │
│  ✓ generate_comparison_pages()(按需)│
│  ✓ extract_zk_candidates()          │
│                                     │
│  输出: IngestResult                 │
└─────────────────────────────────────┘
```

## 使用

```python
from ctw_ingest import LLMWikiIngest
from ctw_types import SourceInput, ClassifyResult, LevelResult, ContentType, InfoLevel

ingest = LLMWikiIngest()

source = SourceInput(
    url="https://github.com/example/tool",
    title="MCP Server",
    description="Model Context Protocol Server",
    content="## Overview\nThis MCP server..."
)

classify = ClassifyResult(
    content_type=ContentType.TOOL_EXTENSION,
    content_type_name="工具拓展",
    confidence=0.85,
)

level = LevelResult(
    level=InfoLevel.L2,
    level_name="Practice Deep-Dive",
)

result = ingest.ingest(source, classify, level)

print(len(result.entity_pages))       # >= 1
print(len(result.comparison_pages))   # >= 1
print(len(result.zk_candidates))      # >= 1
print(result.human_feedback_required) # False
```

## 输出结构

```
llmwiki/wiki/
├── sources/          # 源摘要页 (--type: source-summary)
├── entities/         # 实体页 (--type: entity)
├── concepts/         # 概念页 (--type: concept)
└── comparisons/      # 对比页 (--type: comparison)
```

## 依赖

- `lib/ctw_types.py` — 共享类型定义
- `lib/ctw_config.py` — 配置加载器

## Gate

摄入完成后触发 `APPROVE_OUTPUT` gate，让用户审批产出内容。
