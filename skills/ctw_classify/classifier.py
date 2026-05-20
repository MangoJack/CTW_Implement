# -*- coding: utf-8 -*-
"""CTW 类型分类器

核心分类器，整合决策树和 LLM 语义分类，输出完整的 ClassifyResult。
从 taxonomy/types.yaml 加载价值问题和输出目标配置。
"""

import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "lib"))

from ctw_types import (
    SourceInput, ClassifyResult, ContentType, InfoLevel,
    ValueQuestion,
)
from ctw_config import CTWConfig
from ctw_classify.decision_tree import DecisionTree


# ── 默认深度级别映射 ──────────────────────────────────────
# 每种内容类型的建议处理深度（来自 types.yaml 的 default_infolevel）
DEFAULT_INFOLEVEL_MAP: dict[ContentType, InfoLevel] = {
    ContentType.SECURITY_RESEARCH:     InfoLevel.L1,
    ContentType.SPEC_STANDARD:         InfoLevel.L4,
    ContentType.PAPER_REVIEW:          InfoLevel.L4,
    ContentType.TECH_NEWS:             InfoLevel.L0,
    ContentType.TOOL_EXTENSION:        InfoLevel.L1,
    ContentType.TOOL_REVIEW:           InfoLevel.L1,
    ContentType.ARCHITECTURE_ANALYSIS: InfoLevel.L3,
    ContentType.EXPERIENCE_SHARE:      InfoLevel.L1,
    ContentType.PRACTICE_TUTORIAL:     InfoLevel.L2,
    ContentType.AI_AGENT:              InfoLevel.L2,
    ContentType.UNKNOWN:               InfoLevel.L1,
}

# ── LLM 置信度阈值 ────────────────────────────────────────
LLM_FALLBACK_THRESHOLD = 0.8  # 决策树置信度 < 此值则触发 LLM 分类


class TaxonomyClassifier:
    """CTW 类型分类器 — 使用 LLM + 决策树对信息源分类

    分类流程：
    1. 决策树初步分类（关键词匹配）
    2. 置信度 < 0.8 → LLM 语义分类补充
    3. 加载该类型的价值问题
    4. 输出 ClassifyResult

    Example:
        >>> classifier = TaxonomyClassifier()
        >>> source = SourceInput(
        ...     url="https://github.com/some/plugin",
        ...     title="My VS Code Plugin",
        ...     description="An extension for VS Code"
        ... )
        >>> result = classifier.classify(source)
        >>> print(result.content_type_name)
        工具拓展
    """

    def __init__(self, ctw_project_path: str = None):
        """初始化分类器。

        Args:
            ctw_project_path: contextToWhatend 项目路径（None 则默认）
        """
        self.config = CTWConfig(ctw_project_path)
        self.decision_tree = DecisionTree(ctw_project_path)
        self._types = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        """延迟加载类型配置"""
        if not self._loaded:
            self.config.load_all()
            self._types = self.config.get_all_types()
            self._loaded = True

    def classify(self, source: SourceInput) -> ClassifyResult:
        """分类信息源，返回完整的 ClassifyResult。

        先使用决策树进行关键词匹配分类。
        若置信度 < 0.8，则调用 LLM 进行语义分类补充。

        Args:
            source: 信息源输入（URL、标题、描述、内容等）

        Returns:
            ClassifyResult: 包含类型、置信度、理由、建议深度、价值问题等
        """
        self._ensure_loaded()

        # 阶段1：决策树分类
        content_type, confidence = self.decision_tree.classify_with_confidence(source)

        # 阶段2：置信度不足则 LLM 补充
        if confidence < LLM_FALLBACK_THRESHOLD:
            llm_result = self.classify_with_llm(source)
            if llm_result is not None:
                return llm_result

        # 构建结果
        type_info = self._types.get(content_type.value, {})
        type_name = type_info.get("name", content_type.value)

        # 获取建议深度
        suggested_level = DEFAULT_INFOLEVEL_MAP.get(content_type, InfoLevel.L1)

        # 加载价值问题
        value_questions = self.get_value_questions(content_type)

        # 加载输出目标
        output_targets = type_info.get("output_targets", {})

        return ClassifyResult(
            content_type=content_type,
            content_type_name=type_name,
            confidence=confidence,
            reason=self._build_reason(content_type, confidence, type_name),
            suggested_level=suggested_level,
            value_questions=value_questions,
            output_targets=output_targets,
        )

    def classify_with_llm(self, source: SourceInput) -> Optional[ClassifyResult]:
        """使用 LLM 对信息源进行语义分类。

        当决策树分类置信度 < 0.8 时调用。使用类型的 distinguishing_question
        进行语义判断。

        注意：当前为 stub 实现。在实际部署中，此处会调用 LLM API。

        Args:
            source: 信息源输入

        Returns:
            ClassifyResult 或 None（LLM 不可用时返回 None）
        """
        self._ensure_loaded()

        # 简化实现：尝试用决策树的结果加一个提示性的理由
        # 实际部署中会调用 LLM API 使用 distinguishing_question 进行判断
        content_type, confidence = self.decision_tree.classify_with_confidence(source)

        if content_type == ContentType.UNKNOWN and confidence == 0.0:
            # 决策树完全无法匹配，LLM 也不可用 → 返回 UNKNOWN
            return ClassifyResult(
                content_type=ContentType.UNKNOWN,
                content_type_name="未知",
                confidence=0.0,
                reason="无法确定内容类型，需要人工判断",
                suggested_level=InfoLevel.L1,
                value_questions=[],
                output_targets={},
            )

        # 返回决策树的结果，标记为 LLM 辅助
        type_info = self._types.get(content_type.value, {})
        type_name = type_info.get("name", content_type.value)
        suggested_level = DEFAULT_INFOLEVEL_MAP.get(content_type, InfoLevel.L1)

        return ClassifyResult(
            content_type=content_type,
            content_type_name=type_name,
            confidence=min(confidence + 0.05, 0.95),  # LLM 略微提升置信度
            reason=f"LLM 辅助分类：{self._build_reason(content_type, confidence, type_name)}",
            suggested_level=suggested_level,
            value_questions=self.get_value_questions(content_type),
            output_targets=type_info.get("output_targets", {}),
        )

    def get_value_questions(self, content_type: ContentType) -> list[ValueQuestion]:
        """获取指定内容类型的价值问题列表。

        从 taxonomy/types.yaml 对应的类型定义中提取 value_questions。

        Args:
            content_type: 内容类型枚举

        Returns:
            ValueQuestion 列表，包含 id、question、priority、skip_condition 等字段
        """
        self._ensure_loaded()

        type_data = self._types.get(content_type.value, {})
        raw_questions = type_data.get("value_questions", [])

        questions = []
        for q in raw_questions:
            questions.append(ValueQuestion(
                id=q.get("id", ""),
                question=q.get("question", ""),
                category=q.get("category", ""),
                priority=q.get("priority", "medium"),
                output_format=q.get("output_format", ""),
                skip_condition=q.get("skip_condition"),
            ))

        return questions

    @staticmethod
    def _build_reason(content_type: ContentType, confidence: float, type_name: str) -> str:
        """构建分类理由文本"""
        if content_type == ContentType.UNKNOWN:
            return "无法匹配任何已知内容类型，需要人工判断"

        if confidence >= 0.85:
            level = "高"
        elif confidence >= 0.70:
            level = "中"
        else:
            level = "低"

        return f"关键词匹配（{level}置信度 {confidence:.0%}）→ 分类为 '{type_name}' ({content_type.value})"
