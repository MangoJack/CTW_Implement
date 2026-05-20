# CTW Implement — 复盘报告 + 改进建议 + 使用指南

**生成日期**：2026-05-20 | **作者**：Saturb 🕶️ | **状态**：101/101 测试通过 ✅

---

## 一、项目复盘

### 1.1 项目概览

`CTW_Implement` 是将 `contextToWhatend` (CTW) 项目的核心理念——"每次 AI 对话后产生标准化、结构化、可复用的产出物"——落地为可执行的 Python 管线，实现 **Taxonomy 分类 → InfoLevel 路由 → LLM Wiki 摄入** 三阶段全流程自动化。

### 1.2 执行过程

| 阶段 | 方式 | 结果 | 耗时 |
|------|------|------|------|
| 1. 共享库 | 直接实现 | `lib/` 4个文件，17 test ✅ | ~2min |
| 2. ctw_classify | 子Agent → 31 failure → 手修 | 31 tests ✅ | ~19min (子Agent) + 15min (修复) |
| 3. ctw_infolevel | 子Agent | 25 tests ✅ | ~6min |
| 4. ctw_ingest | 子Agent → 只有测试 → 手写实现 | 17 tests ✅ | ~17min (子Agent) + 10min (手写) |
| 5. ctw_pipeline | 直接实现 | 11 tests ✅ | ~10min |

### 1.3 子 Agent 效能分析

| 子 Agent | 成功？ | 根本原因 |
|----------|:---:|------|
| **ctw_classify** | ❌ | YAML 解析错误阻塞全部测试；子 Agent 耗尽 19min 未修复 |
| **ctw_infolevel** | ✅ | 任务边界清晰，无外部依赖问题 |
| **ctw_ingest** | ❌ | 只写了测试文件，未写 `ingest.py` 实现代码 |

**教训**：
- 子 Agent 在遇到阻塞性外部依赖（如 YAML 解析错误）时容易陷入死循环
- 子 Agent 在 TDD 模式下可能止步于写测试，"等父 Agent 审查后再写实现"的预期未达成
- 对于耦合度高的子任务（classify 依赖 types.yaml），父 Agent 应预检依赖健康度

### 1.4 修复的问题清单

| # | 问题 | 模块 | 修复方式 |
|---|------|------|---------|
| 1 | `types.yaml` L411 `"` 被 YAML 当作 flow scalar 边界 | 上游 | `>` fold block scalar |
| 2 | `extension` 子串匹配 `extensibility` | decision_tree | 英文关键词切换为 `\b` 正则 |
| 3 | `benchmark` 属于 TOOL_REVIEW 但定义在 PAPER_REVIEW | decision_tree | 从 PAPER_REVIEW 移除 |
| 4 | AI_AGENT 优先级低于 ARCHITECTURE_ANALYSIS | decision_tree | 移到 ARCHITECTURE 之前 |
| 5 | `ctw_ingest/ingest.py` 不存在 | ingest | 手写完整实现 |
| 6 | `CTWConfig.__init__` 参数名 `ctw_project_path` ≠ `project_path` | pipeline | 参数名对齐 |
| 7 | pipeline.py 路径深度计算错误（2 层 vs 3 层） | pipeline | 三连 `dirname()` |

---

## 二、改进建议

### 2.1 🔴 高优先级（影响可用性）

#### 2.1.1 接入真实 LLM（当前为 stub）

**现状**：`classifier.py` 的 `classify_with_llm()` 本质上还是调决策树，没有调用任何 LLM API。`ingest.py` 的模板填充是纯字符串格式化，没有 LLM 生成内容。

**建议**：
```python
# classifier.py — 接入 LLM
def classify_with_llm(self, source: SourceInput) -> Optional[ClassifyResult]:
    import openai
    prompt = f"""判断以下信息源的内容类型（10选1）：
标题：{source.title}
描述：{source.description}
内容摘要：{source.content[:2000]}
..."""
    response = openai.chat.completions.create(
        model="deepseek/deepseek-v4-flash",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    return self._parse_llm_response(response)
```

#### 2.1.2 文件系统输出

**现状**：`IngestResult.output_files` 存了目标路径但从未写入磁盘。

**建议**：在 `ingest.py` 添加 `write_to_disk()` 方法，实际创建 `llmwiki/wiki/sources/`、`entities/`、`concepts/`、`comparisons/` 下的 `.md` 文件。

#### 2.1.3 真实 Gate 交互

**现状**：Gates 被创建并记录状态，但没有人机交互环节——`APPROVE_OUTPUT` 和 `APPROVE_ZK` 应该是阻塞等待人类审核才继续的，当前是直接标记 `PENDING_MODIFIED` 然后继续。

**建议**：管线应在 Gate 处挂起，通过 OpenClaw 的 `cron` / `taskflow` 机制等待用户反馈。

### 2.2 🟡 中优先级（增强完整性）

#### 2.2.1 决策树规则外置化

**现状**：10 组关键词硬编码在 `decision_tree.py`，与 `types.yaml` 中的 `distinguishing_question` 重复定义。

**建议**：将关键词规则从 Python 代码移到 `types.yaml`：
```yaml
tool-extension:
  keywords: [plugin, extension, mcp, 插件, add-on, addon]
  keyword_weight: 1.0
```
`decision_tree.py` 从 YAML 动态加载，减少硬编码，保持单一事实来源。

#### 2.2.2 补全 Value Questions 的用途

**现状**：`classifier.get_value_questions()` 正确加载了价值问题，但 `ingest` 阶段完全没有使用它们——没有 "回答类型特定价值问题" 的步骤。

**建议**：在 `ingest()` 中增加 `_answer_value_questions()` 步骤，对每个 `ValueQuestion` 生成回答并合并到产出。

#### 2.2.3 集成已有的 CTW 模板

**现状**：`ingest.py` 硬编码了 4 个内联模板。上游项目 `llmwiki/templates/` 已有 5 个完整模板文件。

**建议**：`ingest.py` 应从 `contextToWhatend/llmwiki/templates/` 读取模板，而非内联。同理，InfoLevel 模板（L0-L5）也应被 router 引用。

#### 2.2.4 缺少 SourceCategory 路径映射

**现状**：`SourceInput.source_type` 接受任意字符串（`video/article/repo/pdf/url/chat`），但 `ingest` 没有根据类型选择 `raw/` 子目录（`raw/articles/`、`raw/papers/`、`raw/transcripts/`）。

**建议**：使用 `SourceCategory` 枚举做映射，`ingest` 自动选择正确的 raw 子目录。

#### 2.2.5 测试覆盖率缺口

**现状**：
- ✅ 分类 31 tests
- ✅ 路由 25 tests
- ✅ 摄入 17 tests
- ✅ 管线 11 tests
- ✅ 共享库 17 tests
- ❌ 缺少：决策树对混合中英文的准确率 benchmark
- ❌ 缺少：LLM fallback 的 mock 测试
- ❌ 缺少：大内容截断/边界测试

### 2.3 🟢 低优先级（工程优化）

#### 2.3.1 包管理标准化

**现状**：依赖 `sys.path.insert()` 手动管理导入路径，4 个模块的 `sys.path` 各不相同。

**建议**：添加 `setup.py` 或 `pyproject.toml`，使 `CTW_Implement` 成为可安装的 Python 包：
```bash
pip install -e .
```
然后 `from ctw_implement.ctw_classify import TaxonomyClassifier`。

#### 2.3.2 配置文件统一

**现状**：`CTWConfig` 硬编码默认路径为 `D:\MainWorkSpace\contextToWhatend`。在不同机器上部署会失败。

**建议**：优先级链：环境变量 `CTW_PROJECT_PATH` > 构造函数参数 > 相对路径自动发现。

#### 2.3.3 异步化准备

**现状**：所有方法都是同步的。LLM 调用会阻塞管线。

**建议**：核心方法提供 `async` 变体（`async def classify_async()`），为 OpenClaw skill 集成做准备。

#### 2.3.4 添加端到端集成测试

**现状**：`test_pipeline.py` 使用简单的 fixture 数据。缺少用真实 URL/B站/GitHub 内容的端到端测试。

**建议**：创建 `tests/integration/` 目录，放入真实场景的 sample 文件做完整管线测试。

---

## 三、完整使用指南

### 3.1 环境要求

```bash
Python >= 3.10
pip install pyyaml  # types.yaml 解析依赖
```

### 3.2 项目结构

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

### 3.3 快速开始（3 种使用方式）

#### 方式 A：完整管线（推荐）

```python
import sys
sys.path.insert(0, r"D:\MainWorkSpace\CTW_Implement")
sys.path.insert(0, r"D:\MainWorkSpace\CTW_Implement\skills\ctw_pipeline")

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

#### 方式 B：分阶段调用

```python
import sys
sys.path.insert(0, r"D:\MainWorkSpace\CTW_Implement")
sys.path.insert(0, r"D:\MainWorkSpace\CTW_Implement\lib")
sys.path.insert(0, r"D:\MainWorkSpace\CTW_Implement\skills\ctw_classify")
sys.path.insert(0, r"D:\MainWorkSpace\CTW_Implement\skills\ctw_infolevel")
sys.path.insert(0, r"D:\MainWorkSpace\CTW_Implement\skills\ctw_ingest")

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

#### 方式 C：手动覆盖（跳过分类/路由）

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

### 3.4 内容类型参考

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

### 3.5 深度等级参考

| 等级 | 名称 | 处理方式 | 典型产出 |
|:---:|------|------|------|
| L0 | Quick Scan | 速览标题+摘要，不深入 | 标记、跳过或升级 |
| L1 | Tool Review | 基本信息采集 | 实体页、基本信息 |
| L2 | Practice Deep-Dive | 深入理解实践内容 | 源摘要 + ZK 候选 |
| L3 | System Analysis | 系统级架构分析 | 实体 + 概念 + 对比 |
| L4 | Research Synthesis | 研究级合成 | 源摘要 + 概念 + ZK 候选 |

### 3.6 产出物路由表

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

### 3.7 Gate 机制

| Gate | 阶段 | 默认状态 | 含义 |
|------|------|------|------|
| `CLASSIFY` | classify | `passed` | 自动通过，记录分类结果 |
| `APPROVE_OUTPUT` | ingest | `pending_modified` | 等待人类审核 ingest 产出 |
| `APPROVE_ZK` | zk | `pending_modified` | 等待人类审核 ZK 候选 |
| `RESOLVE_CONFLICT` | - | - | 笔记冲突时触发 |
| `PROMOTE` | - | - | ZK 候选升级为永久笔记 |
| `CONFIG_CHANGE` | - | - | 配置变更时触发 |

> ⚠️ 当前版本 Gates 仅记录状态，未实现真正的人机交互阻塞等待。需后续集成 OpenClaw 的 `taskflow` / `cron` 机制。

### 3.8 进阶：从代码到 OpenClaw Skill

要将这些 Python 模块部署为真正的 OpenClaw 技能，需要在 `openclaw.json` 中注册：

```json
{
  "skills": {
    "ctw_classify": {
      "path": "D:\\MainWorkSpace\\CTW_Implement\\skills\\ctw_classify",
      "enabled": true
    },
    "ctw_infolevel": {
      "path": "D:\\MainWorkSpace\\CTW_Implement\\skills\\ctw_infolevel",
      "enabled": true
    },
    "ctw_ingest": {
      "path": "D:\\MainWorkSpace\\CTW_Implement\\skills\\ctw_ingest",
      "enabled": true
    },
    "ctw_pipeline": {
      "path": "D:\\MainWorkSpace\\CTW_Implement\\skills\\ctw_pipeline",
      "enabled": true
    }
  }
}
```

注意：当前 skill 的 `SKILL.md` 文件存在但缺少 OpenClaw 所需的完整 skill 入口函数（`run` / `apply` 等）。正式部署前需补充。

### 3.9 运行所有测试

```bash
cd D:\MainWorkSpace\CTW_Implement
python -m pytest skills/ tests/ -v
```

预期输出：`101 passed in ~1.2s`

### 3.10 触发分类的关键词参考

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

## 四、与上游 CTW 项目的差异

| 维度 | CTW Implement | contextToWhatend |
|------|:---:|:---:|
| 范围 | 管线核心（分类+路由+摄入） | 七轨全栈 + 支撑系统 |
| LLM 集成 | ⚠️ stub（无实际调用） | 理论完备，等待实现 |
| 文件输出 | ❌ 仅记录路径，未写盘 | 目录结构已建好 |
| 测试 | ✅ 101/101 | ❌ 无自动化测试 |
| 模板 | 内联硬编码 | `llmwiki/templates/` 5 个文件 |
| Gate 交互 | 仅记录状态 | `workflows/gates.yaml` 完整定义 |
| Harness/CyberRole/CyberEmployee | ❌ 未实现 | ✅ 模板就绪 |
| 去重/冲突处理 | ❌ 未实现 | `design/deduplication-guide.md` 已设计 |

---

*复盘完成。CTW Implement 作为管线核心已就绪（101 tests），下一步是 LLM 集成和文件系统输出。*
