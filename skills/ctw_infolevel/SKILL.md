# SKILL.md — ctw_infolevel

**Skill name:** ctw_infolevel  
**Version:** 1.0.0  
**Description:** CTW 深度路由器 — 根据内容类型确定信息处理深度级别（L0-L4）

## Purpose

The `ctw_infolevel` skill takes the output of `ctw_classify` (a `ClassifyResult`) and
determines the appropriate processing depth level (L0-L4) for the information source.
It enforces per-type maximum levels and supports manual overrides with bounds checking.

## Architecture

```
ctw_infolevel/
├── SKILL.md           # This file
├── __init__.py         # Package exports
├── router.py           # Core routing logic (InfoLevelRouter)
└── tests/
    ├── __init__.py
    └── test_router.py  # Full test suite
```

## Processing Levels

| Level | Name | Description |
|-------|------|-------------|
| L0 | Quick Scan | 速览：低价值信息、新闻、无需深度处理 |
| L1 | Tool Review | 工具评测：工具/插件评估 |
| L2 | Practice Deep-Dive | 实践深挖：教程、方法、深入实践 |
| L3 | System Analysis | 系统分析：大型项目架构、框架 |
| L4 | Research Synthesis | 研究合成：论文、白皮书、高级分析 |

## Default Level by Content Type

| Content Type | Default | Max |
|--------------|---------|-----|
| tool-extension | L1 | L3 |
| tool-review | L1 | L2 |
| practice-tutorial | L2 | L3 |
| architecture-analysis | L3 | L4 |
| paper-review | L4 | L4 |
| tech-news | L0 | L1 |
| experience-share | L1 | L2 |
| spec-standard | L4 | L4 |
| security-research | L1 | L4 |
| ai-agent | L2 | L4 |
| unknown | L1 | L2 |

## Usage

```python
from router import InfoLevelRouter
from ctw_types import ClassifyResult, ContentType, InfoLevel

router = InfoLevelRouter()

# Basic routing
result = ClassifyResult(content_type=ContentType.AI_AGENT, ...)
level = router.route(result)  # → L2

# Manual override (within bounds)
level = router.route(result, manual_override=InfoLevel.L4)  # → L4 (ai-agent max=L4)

# Bounds check
router.can_upgrade(InfoLevel.L2, InfoLevel.L4, ContentType.AI_AGENT)  # → True
router.can_upgrade(InfoLevel.L1, InfoLevel.L3, ContentType.TOOL_REVIEW)  # → False
```

## Testing

```bash
cd CTW_Implement
python -m pytest skills/ctw_infolevel/tests/ -v
```

## Dependencies

- `ctw_types.py` from `lib/`
- Python 3.10+ (uses `dataclasses`, `enum`, `typing.Optional`)

## License

Part of the CTW (contextToWhatend) pipeline.
