---
name: ctw_classify
description: CTW 类型分类器 — 将信息源分类为 10 种内容类型之一
version: "1.0"
---

# CTW Classify

CTW (Context To Workflow) 管线第一阶段：内容类型分类。

## 触发

当用户提供信息源（URL/文件/描述）并需要 CTW 分类时触发。

## 支持的分类

| 类型 | ID | 中文名称 |
|------|-----|---------|
| 安全研究 | security-research | CVE/漏洞/攻击分析 |
| 规范标准 | spec-standard | RFC/W3C/协议规范 |
| 论文解读 | paper-review | 学术论文/白皮书 |
| 技术新闻 | tech-news | 时效性强的新闻/公告 |
| 工具拓展 | tool-extension | 已有工具的插件/扩展 |
| 工具评测 | tool-review | 独立工具的系统性评测 |
| 架构分析 | architecture-analysis | 大型项目源码/架构分析 |
| 经验分享 | experience-share | 个人/团队实践总结 |
| 实践教程 | practice-tutorial | 教程/workshop/手把手 |
| AI Agent | ai-agent | AI Agent 领域内容 |

## 流程

```
SourceInput
    │
    ▼
┌─────────────────┐
│  决策树初步分类   │ ← 关键词匹配 (decision_tree.py)
│  按优先级顺序:    │    security-research → spec-standard →
│                   │    paper-review → tech-news →
│                   │    tool-extension → tool-review →
│                   │    architecture-analysis →
│                   │    experience-share → practice-tutorial
│                   │    → ai-agent → unknown
└────────┬────────┘
         │
    confidence ≥ 0.8?
    ┌────┴────┐
   否         是
    │         │
    ▼         ▼
┌────────┐  ┌──────────────┐
│ LLM    │  │ 直接产出      │
│ 语义分类│  │ ClassifyResult│
└───┬────┘  └──────────────┘
    │
    ▼
ClassifyResult
  ├── content_type
  ├── confidence
  ├── reason
  ├── suggested_level (InfoLevel)
  ├── value_questions (类型特定的价值问题)
  └── output_targets (推荐的输出目标路径)
```

## 使用

```python
from ctw_classify import TaxonomyClassifier
from ctw_types import SourceInput

classifier = TaxonomyClassifier()

source = SourceInput(
    url="https://github.com/example/plugin",
    title="My VS Code Plugin",
    description="An extension for VS Code",
    content="..."
)

result = classifier.classify(source)
# result.content_type == ContentType.TOOL_EXTENSION
# result.confidence == 0.95
# result.suggested_level == InfoLevel.L1
```

## 依赖

- `lib/ctw_types.py` — 共享类型定义
- `lib/ctw_config.py` — 配置加载器
- `contextToWhatend/taxonomy/types.yaml` — 分类法定义
- `pyyaml` — YAML 解析

## 配置

分类器通过 `CTWConfig` 自动加载 `contextToWhatend/taxonomy/types.yaml` 中的所有类型定义、价值问题和输出目标。

可通过环境变量 `CTW_PROJECT_PATH` 覆盖 contextToWhatend 项目路径。

## Gate

分类完成后触发 `CLASSIFY` gate，进入下一阶段深度路由。
