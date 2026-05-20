# CTW Analyzer — 交互优化交付报告

**交付日期**：2026-05-20 | **操作员**：Saturb 🕶️ | **测试**：147/147 ✅

---

## 1. 交付概要

| 项目 | 状态 |
|------|:---:|
| 新增 skill | ✅ `ctw_analyzer` |
| 新增代码 | ✅ `analyzer.py` (~650 行) |
| 新增测试 | ✅ 46 tests |
| CLI 集成 | ✅ `ctw_runner.py ana` |
| Skill 注册 | ✅ `~/.openclaw/skills/ctw_analyzer/SKILL.md` |
| 跨 skill 兼容 | ✅ 101 旧测试无回归 |

---

## 2. 新增功能

### 2.1 `/ctw_ana` 智能交互入口

一条自然语言命令完成所有操作：

```bash
/ctw_ana 帮我分析 https://github.com/user/repo 这个 MCP plugin
/ctw_ana 分析这些论文：https://arxiv.org/a https://arxiv.org/b
```

**自动完成的步骤：**
1. 🔍 从 prompt 提取所有 URL（支持中文标点结尾）
2. 🏷️ 根据域名推断 source_type（9 种域名 → 5 种类型映射）
3. 📊 调用 ctw_classify 决策树 + LLM fallback
4. 🧠 智能决定处理深度（硬规则 + 置信度 + 完整度综合判断）
5. 📝 执行摄入（源摘要 + 实体 + 概念 + 对比）
6. 📋 生成行动建议
7. ❓ 信息不足时自动追问

### 2.2 智能深度决策

| 条件 | 决策 |
|------|------|
| 技术新闻 | 固定 L0 |
| 安全研究 | 固定 L1 |
| 完整度 < 30% | 最高 L0（仅 URL） |
| 完整度 < 60% | 最高 L1 |
| 置信度 < 85% | 降一级 |
| 其他 | 按建议深度全量 |

### 2.3 追问机制

**自动触发追问的条件：**
- 仅有 URL 无标题/内容 → 完整度 < 50%
- 展示：`[+] [url]: 缺少 title, content，请提供更多信息`

**补充后继续：**
```bash
python ctw_runner.py continue --session session.json \
  --supplement '{"url":{"title":"...","content":"..."}}'
```

### 2.4 会话保存与恢复

- 分析状态可保存为 JSON
- 后续补充信息后 `continue` 推进
- `progress` 查看各资料处理状态

### 2.5 Windows 兼容

- 所有 emoji 输出自动转换为 ASCII (`🔍` → `[search]`, `✓` → `V`)
- URL 提取支持中文全角标点（，。、！？；：""（））
- GBK 编码兼容

---

## 3. 文件清单

### 新增文件

| 文件 | 大小 | 说明 |
|------|------|------|
| `skills/ctw_analyzer/__init__.py` | 158 B | Skill 入口 |
| `skills/ctw_analyzer/analyzer.py` | 23.0 KB | 核心分析器（~650 行） |
| `skills/ctw_analyzer/tests/__init__.py` | 0 B | 测试包 |
| `skills/ctw_analyzer/tests/test_analyzer.py` | 13.2 KB | 46 个测试 |
| `~/.openclaw/skills/ctw_analyzer/SKILL.md` | 2.7 KB | OpenClaw Skill 文档 |

### 修改文件

| 文件 | 变更 |
|------|------|
| `~/.openclaw/skills/ctw_runner.py` | +3 个子命令（ana / continue / progress） |

---

## 4. 测试结果

```
147 passed in 1.74s
```

### 测试明细

| 模块 | 测试类 | 数量 | 状态 |
|------|------|:---:|:---:|
| ctw_analyzer | TestUrlExtraction | 5 | ✅ |
| ctw_analyzer | TestSourceTypeInference | 9 | ✅ |
| ctw_analyzer | TestTitleExtraction | 3 | ✅ |
| ctw_analyzer | TestAnalyzePrompt | 3 | ✅ |
| ctw_analyzer | TestQualityAssessment | 4 | ✅ |
| ctw_analyzer | TestAutoDepthDecision | 5 | ✅ |
| ctw_analyzer | TestCTWAnalyzer | 10 | ✅ |
| ctw_analyzer | TestEdgeCases | 7 | ✅ |
| **ctw_analyzer 小计** | | **46** | ✅ |
| ctw_classify | classifier + decision_tree | 31 | ✅ |
| ctw_infolevel | router | 25 | ✅ |
| ctw_ingest | LLM Wiki | 17 | ✅ |
| ctw_pipeline | orchestrator | 11 | ✅ |
| test_lib | shared lib | 17 | ✅ |
| **总计** | | **147** | ✅ |

---

## 5. CLI 使用示例

### 基本分析

```bash
# 单 URL
python ctw_runner.py ana --prompt "帮我分析 https://github.com/user/repo 这个 MCP plugin"

# 多 URL
python ctw_runner.py ana --prompt "分析：https://github.com/a https://arxiv.org/b"

# 先分类再确认
python ctw_runner.py ana --prompt "https://example.com" --ask-first
```

### 会话管理

```bash
# 保存分析状态
python ctw_runner.py ana --prompt "..." --save-session D:\temp\ctw_session.json

# 查看进度
python ctw_runner.py progress --session D:\temp\ctw_session.json

# 补充信息后继续
python ctw_runner.py continue --session D:\temp\ctw_session.json \
  --supplement '{"https://github.com/user/repo":{"title":"MCP Server","content":"## Install\n..."}}'
```

---

## 6. 架构设计

```
┌─────────────────────────────────────────────────────────┐
│                      /ctw_ana                           │
│              人类自然语言 + URL(s)                        │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│                  CTWAnalyzer.analyze()                   │
│                                                         │
│  Phase 1: 解析 prompt → 提取 URL + 意图                   │
│  Phase 2: 为每个 URL 创建 source → 评估质量                │
│  Phase 3: 分类 + 智能深度决策                              │
│  Phase 4: 判断是否需要人类介入（信息不足 / ask-first）      │
│  Phase 5: 执行摄入（自动模式）                             │
│  Phase 6: 生成摘要 + 建议 + 追问                           │
└──────────────────────┬──────────────────────────────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
    ctw_classify  ctw_infolevel  ctw_ingest
    (10 类型)     (L0-L4 路由)   (LLM Wiki)
```

---

## 7. 与现有 Skill 的关系

```
ctw_analyzer (新增)
    ├── 调用 ctw_classify.classifier → ClassifyResult
    ├── 调用 ctw_infolevel.router → LevelResult
    └── 调用 ctw_ingest.ingest → IngestResult

ctw_pipeline (已有)
    └── 底层管线，被 analyzer 复用部分逻辑

ctw_runner (增强)
    ├── classify (已有)
    ├── pipeline (已有)
    ├── ana (新增)      ← /ctw_ana CLI 入口
    ├── continue (新增)  ← 补充信息后继续
    ├── progress (新增)  ← 查看进度
    ├── test (已有)
    └── status (已有)
```

---

*交付完成。CTW 系统现在支持 `/ctw_ana "人类prompt + 链接"` 式的自然交互。*
