# CTW Implement — 完整部署与使用指南

**版本**：1.0 | **日期**：2026-05-20 | **测试**：101/101 ✅

---

## 目录

1. [项目概述](#1-项目概述)
2. [环境要求](#2-环境要求)
3. [安装部署](#3-安装部署)
4. [项目架构](#4-项目架构)
5. [快速上手](#5-快速上手)
6. [API 参考](#6-api-参考)
7. [内容类型与深度等级](#7-内容类型与深度等级)
8. [产出物路由](#8-产出物路由)
9. [Gate 机制](#9-gate-机制)
10. [OpenClaw Skill 部署](#10-openclaw-skill-部署)
11. [测试运行](#11-测试运行)
12. [故障排查](#12-故障排查)
13. [附录](#13-附录)

> 从 CTW Implement 复盘报告中提取，独立保存为使用手册。

## 2. 环境要求

```bash
Python >= 3.10
pip install pyyaml  # types.yaml 解析依赖
```

## 4. 项目架构

```
CTW_Implement/
│
├── lib/                           # 🔧 共享库
│   ├── ctw_types.py               #   所有 dataclass + enum 类型定义
│   ├── ctw_config.py              #   YAML 配置加载器
│   ├── ctw_templates.py           #   模板引擎（预留）
│   └── ctw_output.py              #   文件输出（预留）
│
├── skills/
│   ├── ctw_classify/              # 📦 阶段1：内容类型分类
│   │   ├── SKILL.md               #   技能定义文档
│   │   ├── classifier.py          #   TaxonomyClassifier（决策树 + LLM 补充）
│   │   ├── decision_tree.py       #   DecisionTree（关键词匹配引擎）
│   │   └── tests/                 #   31 个测试
│   │
│   ├── ctw_infolevel/             # 📦 阶段2：深度等级路由
│   │   ├── SKILL.md
│   │   ├── router.py              #   InfoLevelRouter（L0-L4 路由）
│   │   └── tests/                 #   25 个测试
│   │
│   ├── ctw_ingest/                # 📦 阶段3：LLM Wiki 摄入
│   │   ├── SKILL.md
│   │   ├── ingest.py              #   LLMWikiIngest（摘要→实体→概念→对比→ZK）
│   │   └── tests/                 #   17 个测试
│   │
│   └── ctw_pipeline/              # 📦 主控管线编排
│       ├── SKILL.md
│       ├── pipeline.py            #   CTWPipeline（三阶段串联 + Gates）
│       └── tests/                 #   11 个测试
│
├── tests/
│   └── test_lib.py                # 共享库测试（17 个）
│
└── docs/
    └── STATUS.md                  # 状态报告
```

## 5. 快速上手（3 种使用方式）

### 5.1 方式 A：完整管线（推荐）

```python
import sys
sys.path.insert(0, r"<repo>")  # clone root
sys.path.insert(0, r"<repo>/skills/ctw_pipeline")

from pipeline import CTWPipeline, run_pipeline
from ctw_types import SourceInput

# 一行代码
result = run_pipeline({
    "url": "https://github.com/modelcontextprotocol/servers",
    "title": "MCP FileSystem Server",
    "description": "Model Context Protocol server for filesystem access",
    "content": "## Install\nnpm install @modelcontextprotocol/server-filesystem\n\n## Usage\n...",
    "source_type": "article",
})

print(f"类型: {result.classify.content_type_name}")
print(f"深度: {result.level.level_name}")
print(f"产出文件: {result.output_files}")
print(f"ZK候选: {len(result.zk_notes)} 条")
print(f"状态: {result.status}")
```

### 5.2 方式 B：分阶段调用

```python
import sys
sys.path.insert(0, r"<repo>")  # clone root
sys.path.insert(0, r"<repo>/lib")
sys.path.insert(0, r"<repo>/skills/ctw_classify")
sys.path.insert(0, r"<repo>/skills/ctw_infolevel")
sys.path.insert(0, r"<repo>/skills/ctw_ingest")

from ctw_types import SourceInput
from classifier import TaxonomyClassifier
from router import InfoLevelRouter
from ingest import LLMWikiIngest

# 阶段1：分类
source = SourceInput(
    url="https://arxiv.org/abs/2401.12345",
    title="Chain-of-Thought Prompting",
    content="## Abstract\nWe explore how generating a chain of thought...",
    source_type="pdf",
)
classifier = TaxonomyClassifier()
classify_result = classifier.classify(source)
print(f"类型: {classify_result.content_type_name} ({classify_result.confidence:.0%})")

# 阶段2：路由
router = InfoLevelRouter()
level_result = router.route(classify_result)
print(f"深度: {level_result.level_name}")

# 阶段3：摄入
ingest = LLMWikiIngest()
ingest_result = ingest.ingest(source, classify_result, level_result)
print(f"产出: {len(ingest_result.output_files)} 个文件")
```

### 5.3 方式 C：手动覆盖（跳过分类/路由）

```python
from ctw_types import ContentType, InfoLevel, ClassifyResult, LevelResult, SourceInput
from pipeline import CTWPipeline

pipeline = CTWPipeline()
result = pipeline.run(
    SourceInput(title="My Tool", content="..."),
    classify_override=ClassifyResult(
        content_type=ContentType.TOOL_EXTENSION,
        content_type_name="工具拓展",
        confidence=1.0,
    ),
    level_override=LevelResult(
        level=InfoLevel.L2,
        level_name="Practice Deep-Dive",
    ),
)
```

## 7.1 10 种内容类型

| 类型 ID | 中文名 | 默认深度 | 最大深度 | 触发条件 |
|---------|--------|:---:|:---:|------|
| `tool-extension` | 工具拓展 | L1 | L3 | 已有工具的插件/扩展/集成 |
| `tool-review` | 工具评测 | L1 | L2 | 独立工具的系统性评测 |
| `practice-tutorial` | 实践教程 | L2 | L3 | 教程/workshop/手把手 |
| `architecture-analysis` | 架构分析 | L3 | L4 | 大型项目源码/架构分析 |
| `paper-review` | 论文解读 | L4 | L4 | 学术论文/白皮书 |
| `tech-news` | 技术新闻 | L0 | L1 | 时效性强的新闻/公告 |
| `experience-share` | 经验分享 | L1 | L2 | 个人/团队实践总结 |
| `spec-standard` | 规范标准 | L4 | L4 | RFC/W3C/协议规范 |
| `security-research` | 安全研究 | L1 | L4 | CVE/漏洞/攻防分析 |
| `ai-agent` | AI Agent | L2 | L4 | AI Agent 领域内容 |
| `unknown` | 未知 | L1 | L2 | 无法判断时回退 |

## 7.2 5 个深度等级

| 等级 | 名称 | 处理方式 | 典型产出 |
|:---:|------|------|------|
| L0 | Quick Scan | 速览标题+摘要，不深入 | 标记、跳过或升级 |
| L1 | Tool Review | 基本信息采集 | 实体页、基本信息 |
| L2 | Practice Deep-Dive | 深入理解实践内容 | 源摘要 + ZK 候选 |
| L3 | System Analysis | 系统级架构分析 | 实体 + 概念 + 对比 |
| L4 | Research Synthesis | 研究级合成 | 源摘要 + 概念 + ZK 候选 |

## 8. 产出物路由

| 内容类型 | 源摘要 | 实体页 | 概念页 | 对比页 | ZK 候选 |
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

## 9. Gate 机制

| Gate | 阶段 | 默认状态 | 含义 |
|------|------|------|------|
| `CLASSIFY` | classify | `passed` | 自动通过，记录分类结果 |
| `APPROVE_OUTPUT` | ingest | `pending_modified` | 等待人类审核 ingest 产出 |
| `APPROVE_ZK` | zk | `pending_modified` | 等待人类审核 ZK 候选 |
| `RESOLVE_CONFLICT` | - | - | 笔记冲突时触发 |
| `PROMOTE` | - | - | ZK 候选升级为永久笔记 |
| `CONFIG_CHANGE` | - | - | 配置变更时触发 |

> ⚠️ 当前版本 Gates 仅记录状态，未实现真正的人机交互阻塞等待。需后续集成 OpenClaw 的 `taskflow` / `cron` 机制。

## 10. OpenClaw Skill 部署

要将这些 Python 模块部署为真正的 OpenClaw 技能，需要在 `openclaw.json` 中注册：

```json
{
  "skills": {
    "ctw_classify": {
      "path": "<repo>/skills/ctw_classify",
      "enabled": true
    },
    "ctw_infolevel": {
      "path": "<repo>/skills/ctw_infolevel",
      "enabled": true
    },
    "ctw_ingest": {
      "path": "<repo>/skills/ctw_ingest",
      "enabled": true
    },
    "ctw_pipeline": {
      "path": "<repo>/skills/ctw_pipeline",
      "enabled": true
    }
  }
}
```

注意：当前 skill 的 `SKILL.md` 文件存在但缺少 OpenClaw 所需的完整 skill 入口函数（`run` / `apply` 等）。正式部署前需补充。

## 11. 测试运行

```bash
cd CTW_Implement
python -m pytest skills/ tests/ -v
```

预期输出：`101 passed in ~1.2s`

## 13. 附录 — 决策树关键词

以下是在决策树中用于自动分类的关键词（不用 LLM 时的快速匹配）：

**安全研究**：`CVE`, `vulnerability`, `exploit`, `漏洞`, `攻击`
**规范标准**：`RFC`, `specification`, `W3C`, `protocol`, `标准`, `规范`
**论文解读**：`arxiv`, `paper`, `doi`, `abstract`, `论文`, `预印本`
**技术新闻**：`breaking`, `announce`, `release`, `发布`, `推出`
**工具拓展**：`plugin`, `extension`, `MCP`, `插件`, `自定义节点`
**工具评测**：`vs`, `comparison`, `benchmark`, `评测`, `对比`
**架构分析**：`architecture`, `source code`, `pipeline`, `orchestration`, `架构`
**经验分享**：`lessons learned`, `踩坑`, `经验分享`, `实战经验`
**实践教程**：`tutorial`, `how to`, `一步步`, `手把手`, `教程`
**AI Agent**：`ai agent`, `agent framework`, `multi-agent`, `agent 框架`

---