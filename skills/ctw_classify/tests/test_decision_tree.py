# -*- coding: utf-8 -*-
"""决策树分类器测试"""

import pytest
import json
from pathlib import Path

# Add lib to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "lib"))

from ctw_types import SourceInput, ContentType
from ctw_classify.decision_tree import DecisionTree

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixtures():
    """Load test fixtures from JSON"""
    with open(FIXTURES_DIR / "sample_sources.json", "r", encoding="utf-8") as f:
        return json.load(f)["fixtures"]


def _make_source(name: str) -> SourceInput:
    """Create a SourceInput from fixture data by name"""
    fixtures = _load_fixtures()
    data = fixtures[name]
    return SourceInput(
        url=data.get("url", ""),
        title=data.get("title", ""),
        description=data.get("description", ""),
        content=data.get("content", ""),
        source_type=data.get("source_type", ""),
    )


class TestDecisionTree:
    """Test the decision tree classifier"""

    def test_classify_bilibili_mcp_video(self):
        """B站 MCP 插件视频 → tool-extension"""
        source = _make_source("bilibili_mcp_video")
        tree = DecisionTree()
        result = tree.classify(source)
        assert result == ContentType.TOOL_EXTENSION, \
            f"Expected TOOL_EXTENSION, got {result}"

    def test_classify_github_prefect(self):
        """GitHub Prefect 仓库 → architecture-analysis"""
        source = _make_source("github_prefect")
        tree = DecisionTree()
        result = tree.classify(source)
        assert result == ContentType.ARCHITECTURE_ANALYSIS, \
            f"Expected ARCHITECTURE_ANALYSIS, got {result}"

    def test_classify_pdf_paper(self):
        """arXiv 论文 → paper-review"""
        source = _make_source("pdf_paper")
        tree = DecisionTree()
        result = tree.classify(source)
        assert result == ContentType.PAPER_REVIEW, \
            f"Expected PAPER_REVIEW, got {result}"

    def test_classify_security_cve(self):
        """CVE 安全漏洞 → security-research"""
        source = _make_source("security_cve")
        tree = DecisionTree()
        result = tree.classify(source)
        assert result == ContentType.SECURITY_RESEARCH, \
            f"Expected SECURITY_RESEARCH, got {result}"

    def test_classify_n8n_tutorial(self):
        """n8n 教程视频 → practice-tutorial"""
        source = _make_source("n8n_tutorial")
        tree = DecisionTree()
        result = tree.classify(source)
        assert result == ContentType.PRACTICE_TUTORIAL, \
            f"Expected PRACTICE_TUTORIAL, got {result}"

    def test_classify_experience_blog(self):
        """团队经验博客 → experience-share"""
        source = _make_source("experience_blog")
        tree = DecisionTree()
        result = tree.classify(source)
        assert result == ContentType.EXPERIENCE_SHARE, \
            f"Expected EXPERIENCE_SHARE, got {result}"

    def test_classify_unknown(self):
        """空输入 → unknown"""
        source = _make_source("unknown_source")
        tree = DecisionTree()
        result = tree.classify(source)
        assert result == ContentType.UNKNOWN, \
            f"Expected UNKNOWN, got {result}"

    def test_classify_ai_agent_framework(self):
        """AI Agent 框架 → ai-agent"""
        source = _make_source("ai_agent_framework")
        tree = DecisionTree()
        result = tree.classify(source)
        assert result == ContentType.AI_AGENT, \
            f"Expected AI_AGENT, got {result}"

    def test_classify_mcp_spec(self):
        """MCP 协议规范 → spec-standard"""
        source = _make_source("mcp_spec_standard")
        tree = DecisionTree()
        result = tree.classify(source)
        assert result == ContentType.SPEC_STANDARD, \
            f"Expected SPEC_STANDARD, got {result}"

    def test_classify_tool_review_blog(self):
        """API 网关横评 → tool-review"""
        source = _make_source("tool_review_blog")
        tree = DecisionTree()
        result = tree.classify(source)
        assert result == ContentType.TOOL_REVIEW, \
            f"Expected TOOL_REVIEW, got {result}"

    def test_classify_tech_news(self):
        """OpenAI 发布新闻 → tech-news"""
        source = _make_source("tech_news_release")
        tree = DecisionTree()
        result = tree.classify(source)
        assert result == ContentType.TECH_NEWS, \
            f"Expected TECH_NEWS, got {result}"

    def test_confidence_is_float(self):
        """Verify confidence is returned as float 0-1"""
        source = _make_source("bilibili_mcp_video")
        tree = DecisionTree()
        result_type, confidence = tree.classify_with_confidence(source)
        assert isinstance(confidence, float), f"Expected float, got {type(confidence)}"
        assert 0.0 <= confidence <= 1.0, f"Confidence {confidence} out of range"

    def test_all_types_tested(self):
        """Verify we have test cases for all 10 content types + unknown"""
        tree = DecisionTree()
        for fixture_name in _load_fixtures():
            source = _make_source(fixture_name)
            result = tree.classify(source)
            # this just ensures no crash for any fixture
            assert isinstance(result, ContentType)

    def test_loads_taxonomy_from_config(self):
        """Verify DecisionTree loads taxonomy types from CTWConfig"""
        tree = DecisionTree()
        assert tree.types is not None, "types should be loaded"
        assert len(tree.types) >= 10, f"Expected >=10 types, got {len(tree.types)}"
        assert "tool-extension" in tree.types, "Missing tool-extension"

    def test_keyword_match_returns_high_confidence(self):
        """Keyword matching should return confidence >= 0.8"""
        source = _make_source("security_cve")
        tree = DecisionTree()
        _, confidence = tree.classify_with_confidence(source)
        assert confidence >= 0.8, \
            f"Keyword match for CVE should have high confidence, got {confidence}"

    def test_decision_tree_order_respected(self):
        """Security should take priority over other types"""
        # A source that mentions both CVE and AI Agent
        # Should be classified as security-research first
        source = SourceInput(
            title="CVE-2022 AI Agent Framework Vulnerability",
            description="A critical security vulnerability in crewAI agent framework",
            content="CVE-2022-xxxxx affects crewAI versions prior to 0.1.0. This vulnerability allows remote code execution through malicious task payloads. The AI agent framework does not properly sanitize task inputs.",
        )
        tree = DecisionTree()
        result = tree.classify(source)
        assert result == ContentType.SECURITY_RESEARCH, \
            f"Security should take priority, got {result}"
