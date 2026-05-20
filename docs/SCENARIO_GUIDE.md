# CTW Implement — 场景化上手指南

**日期**：2026-05-20 | **状态**：101/101 测试通过 ✅

---

## CTW 做什么

统一流程：**扔进来一个信息源（URL / 文件 / 贴段文字），告诉你这是什么类型、该读多深、该产出什么。**

---

## 🎬 四个典型场景

### 场景 1：「每天刷 RSS，信息过载」

**工作流：快速分诊**

浏览到的链接 → classify 一行命令 → 看类型 + 建议深度 → 决定读不读

```bash
python ~/.openclaw/skills/ctw_runner.py classify \
  "https://example.com/new-mcp-tool" \
  "一个新 MCP 工具发布" \
  --source-type article
```

输出告诉你：`工具拓展 L1` → 只需浅读，记录基本信息。如果是 `论文解读 L4` → 标记下来周末精读。

---

### 场景 2：「想深入学一个新工具 / 框架」

**工作流：工具评测 → 对比 → 纳入知识库**

```
1. classify  → 确认为 工具拓展 / 工具评测
2. 手动覆盖深度（L1 → L3 系统分析）
3. pipeline → 自动生成：源摘要 + 实体页 + 同类对比页 + ZK 候选笔记
```

在 OpenClaw 对话中直接运行：

```python
import sys
sys.path.insert(0, r"D:\MainWorkSpace\CTW_Implement")
sys.path.insert(0, r"D:\MainWorkSpace\CTW_Implement\lib")
sys.path.insert(0, r"D:\MainWorkSpace\CTW_Implement\skills")
sys.path.insert(0, r"D:\MainWorkSpace\CTW_Implement\skills\ctw_pipeline")

from pipeline import run_pipeline

result = run_pipeline({
    "url": "https://github.com/user/new-agent-framework",
    "title": "CrewAI - Multi-Agent Framework",
    "description": "Role-based AI agent orchestration",
    "content": "## Overview\nCrewAI enables...\n## ZK Atomic Candidates\n- [ ] Role-based agent design pattern\n- [ ] 多 Agent 协作的通信协议对比",
})
print(f"类型: {result.classify.content_type_name}, 深度: {result.level.level_name}")
print(f"产出文件: {result.output_files}")
print(f"ZK 候选: {len(result.zk_notes)} 条")
```

---

### 场景 3：「看到一篇重要论文 / 白皮书」

**工作流：深度解读**

```
1. classify → 确认为 论文解读 L4
2. pipeline 全流程 → 生成源摘要 + 概念页 + ZK 候选
3. 手动审核 ZK 候选 → 挑有价值的升级为永久笔记
```

CLI 一行搞定：

```bash
python ~/.openclaw/skills/ctw_runner.py pipeline --json '{
  "url": "https://arxiv.org/abs/2401.12345",
  "title": "Chain-of-Thought Prompting Improves Reasoning",
  "description": "Landmark paper on chain-of-thought in LLMs",
  "content": "## Abstract\nWe demonstrate...\n## ZK Atomic Candidates\n- [ ] CoT 对推理能力提升的量化证据\n- [ ] Few-shot vs Zero-shot CoT 效果对比",
  "source_type": "pdf"
}'
```

---

### 场景 4：「给 n8n / OpenClaw / Claude Code 配新插件」

**工作流：工具拓展 → 部署评估**

```
1. classify → 确认为 工具拓展 L1
2. 查看 value_questions（自动生成的关键问题列表）
3. 按问题逐项回答 → 决定是否部署
```

分类后自动得到的 5 个价值问题：

| 优先级 | ID | 问题 |
|:---:|------|------|
| 🔴 | current_config | 当前是否已有同类扩展？配置状态如何？ |
| 🔴 | fresh_deploy | 全新部署需要哪些步骤？（依赖→安装→配置→验证） |
| 🟡 | similar_tools | 是否有功能类似的替代工具？列出 ≥3 个 |
| 🟡 | capability_compare | 与已知同类工具的核心能力差异？ |
| 🟢 | integration_fit | 集成到当前工作流的可行性？ |

---

## 🗺️ 完整流程决策树

```
你拿到一个信息源
        │
        ▼
   ┌─────────┐
   │ classify │  ← 这是什么？
   └────┬─────┘
        │
   ┌────┴────┐
   │          │
  L0/L1     L2/L3/L4
 速览跳过   值得深入
   │          │
   │     ┌────┴────┐
   │     │          │
   │  pipeline   手动覆盖深度
   │  全流程     再跑 pipeline
   │     │          │
   │     ▼          ▼
   │  ┌──────────────┐
   │  │  产出物清单   │
   │  │ 源摘要 实体页  │
   │  │ 概念页 对比页  │
   │  │ ZK 候选笔记   │
   │  └──────┬───────┘
   │         │
   │    Gate: 审核
   │         │
   │    ┌────┴────┐
   │    │          │
   │  APPROVE    REJECT
   │  入库 ZK    丢弃/修改
   │
   └── 下一个信息源
```

---

## ⚡ 最快的三个起步动作

```bash
# 1. 试分类一个 URL
python ~/.openclaw/skills/ctw_runner.py classify \
  "https://github.com/n8n-io/n8n" "n8n workflow automation" \
  --source-type repo

# 2. 跑完整管线（JSON 输入）
python ~/.openclaw/skills/ctw_runner.py pipeline --json '{
  "url": "https://example.com/tool",
  "title": "测试工具",
  "content": "## Overview\nThis is a test tool..."
}'

# 3. 确认一切正常
python ~/.openclaw/skills/ctw_runner.py status
```

---

## 📋 速查：10 种类型 × 建议动作

| 分类结果 | 默认深度 | 你的动作 |
|---------|:---:|------|
| **安全研究** | L1 | 看 CVE 编号 + 影响范围，决定是否立即处理 |
| **技术新闻** | L0 | 扫一眼标题，有价值升级为实践教程 |
| **工具拓展** | L1 | 看 value_questions，判断是否值得部署 |
| **工具评测** | L1 | 存对比信息，有需要时升级 L3 深入分析 |
| **经验分享** | L1 | 快速提取反模式/教训，归档到 ZK |
| **实践教程** | L2 | 跟着走一遍，提取关键步骤到 ZK |
| **AI Agent** | L2 | 与已有 agent 框架对比，提取设计模式 |
| **架构分析** | L3 | 深度读，提取架构决策 + 概念模型 |
| **论文解读** | L4 | 精读，提取核心论点 + 证据 → ZK |
| **规范标准** | L4 | 精读关键章节，建立术语索引 |

---

## 🔧 四种调用方式

### 方式 A：CLI（一行命令）
```bash
python ~/.openclaw/skills/ctw_runner.py classify <url> <title>
python ~/.openclaw/skills/ctw_runner.py pipeline --json '{...}'
python ~/.openclaw/skills/ctw_runner.py status
python ~/.openclaw/skills/ctw_runner.py test
```

### 方式 B：OpenClaw 对话中 Python
```python
import sys
sys.path.insert(0, r"D:\MainWorkSpace\CTW_Implement")
sys.path.insert(0, r"D:\MainWorkSpace\CTW_Implement\lib")
sys.path.insert(0, r"D:\MainWorkSpace\CTW_Implement\skills")
sys.path.insert(0, r"D:\MainWorkSpace\CTW_Implement\skills\ctw_pipeline")

from pipeline import run_pipeline
result = run_pipeline({"url": "...", "title": "...", "content": "..."})
```

### 方式 C：分阶段精细控制
```python
# 阶段1：只分类
from ctw_classify.classifier import TaxonomyClassifier
from ctw_types import SourceInput

r = TaxonomyClassifier().classify(SourceInput(url="...", title="..."))
# 阶段2：路由深度（可手动升降级）
from ctw_infolevel.router import InfoLevelRouter
router = InfoLevelRouter()
level = router.override(r, InfoLevel.L3)  # 手动升到 L3
# 阶段3：摄入
from ctw_ingest.ingest import LLMWikiIngest
ingest = LLMWikiIngest().ingest(source, r, level)
```

### 方式 D：通过 bootstrap 快捷导入
```python
exec(open(r"C:\Users\MilesF\.openclaw\skills\ctw_bootstrap.py").read())
from classifier import TaxonomyClassifier
from pipeline import run_pipeline
```

---

## 📊 5 个处理深度等级

| 等级 | 名称 | 处理方式 | 典型产出 |
|:---:|------|------|------|
| L0 | Quick Scan | 速览标题+摘要 | 标记、跳过或升级 |
| L1 | Tool Review | 基本信息采集 | 实体页 |
| L2 | Practice Deep-Dive | 深入理解实践内容 | 源摘要 + ZK 候选 |
| L3 | System Analysis | 系统级架构分析 | 实体 + 概念 + 对比 |
| L4 | Research Synthesis | 研究级合成 | 源摘要 + 概念 + ZK |

---

## 📂 产出物路由矩阵

| 内容类型 | 源摘要 | 实体页 | 概念页 | 对比页 | ZK候选 |
|---------|:---:|:---:|:---:|:---:|:---:|
| tool-extension | ✓ | ✓ | — | ✓ | ✓ |
| tool-review | ✓ | ✓ | — | ✓ | ✓ |
| practice-tutorial | ✓ | — | — | — | ✓ |
| architecture-analysis | ✓ | ✓ | ✓ | ✓ | ✓ |
| paper-review | ✓ | — | ✓ | — | ✓ |
| tech-news | ✓ | — | — | — | ✓ |
| experience-share | ✓ | — | — | — | ✓ |
| spec-standard | ✓ | — | — | — | ✓ |
| security-research | ✓ | ✓ | — | ✓ | ✓ |
| ai-agent | ✓ | ✓ | — | ✓ | ✓ |

---

## 🚪 Gate 机制

| Gate | 阶段 | 当前状态 | 人类动作 |
|------|------|------|------|
| CLASSIFY | classify | passed | 自动通过 |
| APPROVE_OUTPUT | ingest | pending_modified | 审核 wiki 产出 |
| APPROVE_ZK | zk | pending_modified | 审核 ZK 候选 |

---

## ⚠️ 当前限制

| 问题 | 说明 |
|------|------|
| LLM 分类 stub | `classify_with_llm()` 未接入真实 API，置信度 <0.8 时使用 LLM fallback 文案 |
| 文件未写盘 | `output_files` 仅记录路径，未实际创建 .md 文件 |
| Gate 未阻塞 | APPROVE gates 仅记录状态，需手动审核 |

---

*CTW Implement — 场景化上手指南 · 2026-05-20 · Saturb 🕶️*
