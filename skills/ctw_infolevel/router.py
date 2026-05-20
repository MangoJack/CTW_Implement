# -*- coding: utf-8 -*-
"""
CTW InfoLevel Router

Determines the processing depth level (L0-L4) for an information source.
Takes a ClassifyResult from ctw_classify and routes to the appropriate InfoLevel.

Supports manual overrides with bounds checking via can_upgrade().
"""
from pathlib import Path
import sys
from typing import Optional

# Ensure lib/ is on sys.path so ctw_types is importable.
_lib_dir = str(Path(__file__).resolve().parent.parent.parent / "lib")
if _lib_dir not in sys.path:
    sys.path.insert(0, _lib_dir)

from ctw_types import (
    ClassifyResult,
    ContentType,
    InfoLevel,
    LevelResult,
)

# ---------------------------------------------------------------------------
# Level metadata
# ---------------------------------------------------------------------------

LEVEL_REASONS: dict[InfoLevel, str] = {
    InfoLevel.L0: "低价值信息/新闻 → 速览（L0 Quick Scan）",
    InfoLevel.L1: "工具/插件评估 → 基本信息采集（L1 Tool Review）",
    InfoLevel.L2: "实践教程/方法 → 深度理解（L2 Practice Deep-Dive）",
    InfoLevel.L3: "大型项目架构 → 系统分析（L3 System Analysis）",
    InfoLevel.L4: "论文/白皮书 → 研究合成（L4 Research Synthesis）",
}

# Default level per content type — derived from taxonomy/types.yaml v1.0
DEFAULT_LEVEL: dict[ContentType, InfoLevel] = {
    ContentType.TOOL_EXTENSION:        InfoLevel.L1,
    ContentType.TOOL_REVIEW:           InfoLevel.L1,
    ContentType.PRACTICE_TUTORIAL:     InfoLevel.L2,
    ContentType.ARCHITECTURE_ANALYSIS: InfoLevel.L3,
    ContentType.PAPER_REVIEW:          InfoLevel.L4,
    ContentType.TECH_NEWS:             InfoLevel.L0,
    ContentType.EXPERIENCE_SHARE:      InfoLevel.L1,
    ContentType.SPEC_STANDARD:         InfoLevel.L4,
    ContentType.SECURITY_RESEARCH:     InfoLevel.L1,
    ContentType.AI_AGENT:              InfoLevel.L2,
    ContentType.UNKNOWN:               InfoLevel.L1,
}

# Maximum allowed level per content type (clamp override upgrades)
MAX_LEVEL: dict[ContentType, InfoLevel] = {
    ContentType.TOOL_EXTENSION:        InfoLevel.L3,
    ContentType.TOOL_REVIEW:           InfoLevel.L2,
    ContentType.PRACTICE_TUTORIAL:     InfoLevel.L3,
    ContentType.ARCHITECTURE_ANALYSIS: InfoLevel.L4,
    ContentType.PAPER_REVIEW:          InfoLevel.L4,
    ContentType.TECH_NEWS:             InfoLevel.L1,
    ContentType.EXPERIENCE_SHARE:      InfoLevel.L2,
    ContentType.SPEC_STANDARD:         InfoLevel.L4,
    ContentType.SECURITY_RESEARCH:     InfoLevel.L4,
    ContentType.AI_AGENT:              InfoLevel.L4,
    ContentType.UNKNOWN:               InfoLevel.L2,
}


def _level_idx(level: InfoLevel) -> int:
    """Extract numeric index from InfoLevel enum (L0→0, L4→4)."""
    return int(level.value[1])


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

class InfoLevelRouter:
    """CTW 深度路由器 — 确定信息处理深度。

    Takes the output of ctw_classify (a ClassifyResult) and determines
    the appropriate processing depth level, respecting per-type maximums.
    Supports manual overrides within type-specific bounds.
    """

    def __init__(self) -> None:
        self.level_reasons: dict[InfoLevel, str] = LEVEL_REASONS

    # ── routing ───────────────────────────────────────────────────────

    def route(
        self,
        classify_result: ClassifyResult,
        manual_override: Optional[InfoLevel] = None,
    ) -> LevelResult:
        """Route a classified source to its processing depth level.

        Args:
            classify_result: Output from the ctw_classify step.
            manual_override: Optional user-requested level override.

        Returns:
            LevelResult with the resolved level, reason, and template path.
        """
        content_type = classify_result.content_type
        default_level = DEFAULT_LEVEL.get(content_type, InfoLevel.L1)

        # Determine final level
        if manual_override is not None and self.can_upgrade(
            default_level, manual_override, content_type
        ):
            level = manual_override
        else:
            level = default_level

        level_value = level.value
        reason = self.level_reasons.get(level, "")

        return LevelResult(
            level=level,
            level_name=level_value,
            confidence=classify_result.confidence,
            reason=reason,
            template=f"output/{level_value.lower()}/template.md",
            processing_steps=[],
        )

    # ── bounds checking ────────────────────────────────────────────────

    def can_upgrade(
        self,
        current: InfoLevel,
        target: InfoLevel,
        content_type: ContentType,
    ) -> bool:
        """Check whether *target* is a valid level for *content_type*.

        - Downgrades (target <= current) are always allowed.
        - Upgrades (target > current) must stay within the type's max level.

        Args:
            current: The current/default level for this source.
            target:  The desired (override) level.
            content_type: The content type classification.

        Returns:
            True if the target level is reachable.
        """
        max_level = MAX_LEVEL.get(content_type, InfoLevel.L2)

        target_idx = _level_idx(target)
        current_idx = _level_idx(current)

        # Downgrade or same level: always allowed
        if target_idx <= current_idx:
            return True

        # Upgrade: must not exceed the type's ceiling
        return target_idx <= _level_idx(max_level)
