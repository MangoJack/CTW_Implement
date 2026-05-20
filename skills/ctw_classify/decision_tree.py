# -*- coding: utf-8 -*-
"""CTW 决策树分类器

遵循 taxonomy/types.yaml 中定义的决策树顺序，使用关键词匹配 + 置信度
对信息源进行确定性分类。决策树是分类的第一阶段，置信度低于阈值时
由 classifier.py 使用 LLM 进行语义分类补充。
"""

import re
import sys
from pathlib import Path
from typing import Optional

# Ensure lib is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "lib"))

from ctw_types import SourceInput, ContentType
from ctw_config import CTWConfig


# ── 关键词规则表 ──────────────────────────────────────────
# 按决策树顺序排列。每个类型包含关键词列表和匹配权重。
# 搜索范围：title + description + content（全部转为小写匹配）

KEYWORD_RULES: list[tuple[ContentType, list[str]]] = [
    # 1. 安全研究 — CVE/漏洞/攻击 优先级最高
    (ContentType.SECURITY_RESEARCH, [
        "cve-", "cve ", "vulnerability", "exploit", "backdoor",
        "cvss", "supply chain attack", "remote code execution",
        "zero-day", "0day", "漏洞", "攻击链", "后门", "安全漏洞",
        "缓冲区溢出", "提权", "sql注入", "xss", "csrf",
    ]),
    # 2. 规范标准 — RFC/W3C/协议规范
    (ContentType.SPEC_STANDARD, [
        "rfc", "w3c", "ietf", "specification", "protocol specification",
        "规范", "协议规范", "标准文档", "technical standard",
        "json-rpc", "openapi spec", "swagger spec",
    ]),
    # 3. 论文解读 — 学术论文/白皮书
    (ContentType.PAPER_REVIEW, [
        "arxiv", "paper", "preprint", "journal", "conference",
        "doi", "abstract", "et al.", "propose a new",
        "论文", "预印本", "学术论文", "白皮书", "white paper",
        "state-of-the-art", "ablation",
    ]),
    # 4. 技术新闻 — 时效性强的新闻/公告
    (ContentType.TECH_NEWS, [
        "announced", "released", "launching", "new version",
        "breaking change", "deprecated", "now available",
        "发布", "公告", "上线", "推出", "正式发布",
        "openai 发布", "google 发布", "微软 发布",
    ]),
    # 5. 工具拓展 — 插件/扩展/集成
    (ContentType.TOOL_EXTENSION, [
        "plugin", "extension", "mcp ", "mcp插件", "mcp 插件",
        "插件", "拓展", "扩展包", "custom node", "自定义节点",
        "integration for", "add-on", "addon",
        "browser extension", "vscode extension", "chrome extension",
    ]),
    # 6. 工具评测 — 独立工具的系统性评测
    (ContentType.TOOL_REVIEW, [
        "comparison", "benchmark", " vs ", "versus", "compared to",
        "evaluation", "review", "评测", "对比", "横评", "测评",
        "which one", "better than", "alternative to",
    ]),
    # 7. AI Agent 方法论 — 在架构分析之前，因为 agent framework 更具体
    (ContentType.AI_AGENT, [
        "ai agent", "agent framework", "llm agent",
        "multi-agent", "multi agent", "agent 框架",
        "agent 编排", "agent 架构", "prompt engineering",
        "tool calling", "tool use", "function calling",
        "agent orchestration", "autonomous agent", "agent swarm",
        "role-playing agent", "agentic",
    ]),
    # 8. 架构分析 — 大型项目架构深度分析
    (ContentType.ARCHITECTURE_ANALYSIS, [
        "architecture", "design pattern", "source code",
        "module design", "api design", "engine",
        "架构", "源码分析", "设计模式", "模块设计",
        "core engine", "pipeline", "orchestration",
        "state machine", "plugin system",
        "task scheduling", "dag", "distributed execution",
    ]),
    # 9. 经验分享 — 个人/团队实操经验
    (ContentType.EXPERIENCE_SHARE, [
        "lessons learned", "lessons learnt", "we learned",
        "我们的经验", "踩坑", "教训", "经验分享",
        "mistake", "pitfall", "counterintuitive",
        "how we", "our experience", "in production",
        "我们团队", "实战经验", "production experience",
    ]),
    # 10. 实践教程 — 教程/workshop
    (ContentType.PRACTICE_TUTORIAL, [
        "tutorial", "workshop", "how to", "step by step",
        "一步步", "从零", "手把手", "教程",
        "实战教程", "入门", "上手", "quickstart",
        "getting started", "build a", "create a",
    ]),
]


class DecisionTree:
    """CTW 决策树分类器

    按照 taxonomy/types.yaml 中定义的顺序遍历决策分支。
    每个分支通过关键词匹配判断类型归属。
    返回 ContentType 枚举值和置信度 (0.0-1.0)。
    """

    def __init__(self, ctw_project_path: str = None):
        """初始化决策树，加载类型配置。

        Args:
            ctw_project_path: contextToWhatend 项目路径。None 则使用默认路径。
        """
        self.config = CTWConfig(ctw_project_path)
        self.types = {}
        self._load_types()

    def _load_types(self) -> None:
        """从 CTWConfig 加载 taxonomy 类型定义"""
        self.config.load_all()
        self.types = self.config.get_all_types()

    def _build_search_text(self, source: SourceInput) -> str:
        """构建用于关键词搜索的文本（lowercase）"""
        parts = [source.title, source.description, source.content]
        return " ".join(p for p in parts if p).lower()

    def _count_keywords(self, text: str, keywords: list[str]) -> tuple[int, int]:
        """统计关键词匹配数量。

        ASCII 关键词使用 word-boundary 匹配以避免子串误匹配
        （如 "extension" 不会匹配 "extensibility"）。
        中文关键词使用普通子串匹配。

        Returns:
            (匹配的关键词数量, 关键词列表长度)
        """
        count = 0
        for kw in keywords:
            kw_lower = kw.lower()
            # ASCII-only keyword: use word boundary to avoid substring false positives
            if all(c.isascii() for c in kw):
                if re.search(r'(?<!\w)' + re.escape(kw_lower) + r'(?!\w)', text):
                    count += 1
            else:
                # Non-ASCII (Chinese etc.): simple substring match
                if kw_lower in text:
                    count += 1
        return count, len(keywords)

    def _keyword_confidence(self, text: str, keywords: list[str]) -> float:
        """基于关键词匹配率计算置信度。

        - 匹配率 >= 30%: 0.95
        - 匹配率 >= 20%: 0.85
        - 匹配率 >= 10%: 0.75
        - 其他: 0.0 (不适配)
        """
        matched, total = self._count_keywords(text, keywords)
        if total == 0:
            return 0.0
        ratio = matched / total
        if ratio >= 0.30:
            return 0.95
        elif ratio >= 0.20:
            return 0.85
        elif ratio >= 0.10 or matched >= 1:
            return 0.75
        else:
            return 0.0

    def classify(self, source: SourceInput) -> ContentType:
        """分类信息源，返回内容类型。

        按决策树顺序遍历，返回第一个匹配的类型。
        若无匹配则返回 UNKNOWN。
        """
        content_type, _ = self.classify_with_confidence(source)
        return content_type

    def classify_with_confidence(self, source: SourceInput) -> tuple[ContentType, float]:
        """分类信息源，返回 (内容类型, 置信度)。

        遍历所有关键词分支，选择置信度最高的类型。
        实现"最高置信度 + 顺序打破平局"策略而非简单的"第一个匹配"策略，
        避免关键词重叠导致误分类。
        置信度范围 0.0-1.0，基于关键词匹配率。
        若所有分支都不匹配，返回 (UNKNOWN, 0.0)。
        """
        text = self._build_search_text(source)

        # 检测 URL 类型提示
        url_lower = source.url.lower()

        # 特殊处理：arxiv URL → paper-review
        if "arxiv.org" in url_lower:
            return ContentType.PAPER_REVIEW, 0.95

        # 特殊处理：nvd.nist.gov URL → security-research
        if "nvd.nist.gov" in url_lower or "cve-" in url_lower:
            return ContentType.SECURITY_RESEARCH, 0.95

        # 特殊处理：spec.* URL 模式 → spec-standard
        if re.search(r'spec\.\w+\.\w+', url_lower):
            return ContentType.SPEC_STANDARD, 0.85

        # 计算所有类型的关键词置信度，选择最高的
        best_type = ContentType.UNKNOWN
        best_confidence = 0.0

        for content_type, keywords in KEYWORD_RULES:
            confidence = self._keyword_confidence(text, keywords)
            if confidence > best_confidence:
                best_confidence = confidence
                best_type = content_type

        return best_type, best_confidence

    def get_best_match(self, source: SourceInput, min_confidence: float = 0.0) -> Optional[ContentType]:
        """获取最佳匹配类型（可设最小置信度阈值）。

        Args:
            source: 信息源
            min_confidence: 最小置信度过滤

        Returns:
            匹配的 ContentType，若无达标匹配则返回 None
        """
        content_type, confidence = self.classify_with_confidence(source)
        if content_type != ContentType.UNKNOWN and confidence >= min_confidence:
            return content_type
        return None
