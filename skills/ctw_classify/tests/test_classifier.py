# -*- coding: utf-8 -*-
"""Core 分类器测试"""

import pytest
import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "lib"))

from ctw_types import SourceInput, ContentType, ClassifyResult, ValueQuestion
from ctw_classify.classifier import TaxonomyClassifier

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixtures():
    with open(FIXTURES_DIR / "sample_sources.json", "r", encoding="utf-8") as f:
        return json.load(f)["fixtures"]


def _make_source(name: str) -> SourceInput:
    fixtures = _load_fixtures()
    data = fixtures[name]
    return SourceInput(
        url=data.get("url", ""),
        title=data.get("title", ""),
        description=data.get("description", ""),
        content=data.get("content", ""),
        source_type=data.get("source_type", ""),
    )


class TestTaxonomyClassifier:
    """Test the full TaxonomyClassifier"""

    def test_classify_bilibili_mcp_video(self):
        """B站 MCP 视频 → tool-extension"""
        source = _make_source("bilibili_mcp_video")
        classifier = TaxonomyClassifier()
        result = classifier.classify(source)
        assert isinstance(result, ClassifyResult)
        assert result.content_type == ContentType.TOOL_EXTENSION
        assert result.content_type_name != ""
        assert result.confidence > 0
        assert result.reason != ""

    def test_classify_github_prefect(self):
        """GitHub Prefect → architecture-analysis"""
        source = _make_source("github_prefect")
        classifier = TaxonomyClassifier()
        result = classifier.classify(source)
        assert result.content_type == ContentType.ARCHITECTURE_ANALYSIS

    def test_classify_pdf_paper(self):
        """PDF 论文 → paper-review"""
        source = _make_source("pdf_paper")
        classifier = TaxonomyClassifier()
        result = classifier.classify(source)
        assert result.content_type == ContentType.PAPER_REVIEW

    def test_classify_security_cve(self):
        """CVE 安全 → security-research"""
        source = _make_source("security_cve")
        classifier = TaxonomyClassifier()
        result = classifier.classify(source)
        assert result.content_type == ContentType.SECURITY_RESEARCH

    def test_classify_n8n_tutorial(self):
        """n8n 教程 → practice-tutorial"""
        source = _make_source("n8n_tutorial")
        classifier = TaxonomyClassifier()
        result = classifier.classify(source)
        assert result.content_type == ContentType.PRACTICE_TUTORIAL

    def test_classify_experience_blog(self):
        """经验分享 → experience-share"""
        source = _make_source("experience_blog")
        classifier = TaxonomyClassifier()
        result = classifier.classify(source)
        assert result.content_type == ContentType.EXPERIENCE_SHARE

    def test_classify_unknown(self):
        """空输入 → unknown"""
        source = _make_source("unknown_source")
        classifier = TaxonomyClassifier()
        result = classifier.classify(source)
        assert result.content_type == ContentType.UNKNOWN
        assert result.confidence >= 0  # even unknown gets a confidence

    def test_classify_ai_agent_framework(self):
        """AI Agent 框架 → ai-agent"""
        source = _make_source("ai_agent_framework")
        classifier = TaxonomyClassifier()
        result = classifier.classify(source)
        assert result.content_type == ContentType.AI_AGENT

    def test_classify_with_llm_fallback(self):
        """When keyword match fails, LLM fallback is attempted"""
        source = SourceInput(
            url="https://example.com/ambiguous",
            title="Some ambiguous content",
            description="This could be anything",
            content="This content doesn't have clear keywords for classification. It discusses software development practices in a general sense.",
        )
        classifier = TaxonomyClassifier()
        result = classifier.classify(source)
        # Should still produce a result (either keyword match or LLM fallback)
        assert isinstance(result, ClassifyResult)
        assert result.content_type in ContentType
        assert result.reason != ""

    def test_value_questions_loaded(self):
        """Value questions are loaded for each content type"""
        classifier = TaxonomyClassifier()

        for ct in ContentType:
            if ct == ContentType.UNKNOWN:
                continue  # unknown may not have value questions
            questions = classifier.get_value_questions(ct)
            assert isinstance(questions, list), \
                f"Value questions for {ct} should be a list"
            # Each type should have at least 2 value questions
            assert len(questions) >= 2, \
                f"Expected >=2 value questions for {ct}, got {len(questions)}"

            # Verify each question has required fields
            for q in questions:
                assert isinstance(q, ValueQuestion), \
                    f"Expected ValueQuestion, got {type(q)}"
                assert q.id != "", f"Question for {ct} has empty id"
                assert q.question != "", f"Question for {ct} has empty question"
                assert q.priority in ("critical", "high", "medium"), \
                    f"Invalid priority {q.priority} for {q.id}"

    def test_value_questions_skip_conditions(self):
        """Value questions include skip_condition where applicable"""
        classifier = TaxonomyClassifier()
        questions = classifier.get_value_questions(ContentType.TOOL_EXTENSION)
        # tool-extension's fresh_deploy should have a skip_condition
        deploy_q = [q for q in questions if q.id == "fresh_deploy"]
        assert len(deploy_q) == 1
        assert deploy_q[0].skip_condition is not None, \
            "fresh_deploy should have skip_condition"

    def test_classify_returns_suggested_level(self):
        """ClassifyResult includes suggested InfoLevel"""
        source = _make_source("github_prefect")
        classifier = TaxonomyClassifier()
        result = classifier.classify(source)
        # architecture-analysis should suggest L3
        assert result.suggested_level is not None
        assert result.suggested_level.value in ("L0", "L1", "L2", "L3", "L4")

    def test_classify_all_fixtures(self):
        """All fixtures classify without errors"""
        classifier = TaxonomyClassifier()
        fixtures = _load_fixtures()
        for name in fixtures:
            source = _make_source(name)
            result = classifier.classify(source)
            assert isinstance(result, ClassifyResult), \
                f"Fixture '{name}' failed to produce ClassifyResult"
            assert result.content_type is not None, \
                f"Fixture '{name}' got None content_type"

    def test_duplicate_source_types(self):
        """Sources that overlap categories are handled correctly"""
        # A source that is both a tool review AND AI agent related
        source = SourceInput(
            url="https://example.com",
            title="LangChain vs CrewAI: AI Agent Framework Comparison 2024",
            description="Systematic comparison of two AI agent frameworks",
            content="We evaluate LangChain and CrewAI across 10 dimensions: agent architecture, tool integration, memory systems, multi-agent coordination...",
        )
        classifier = TaxonomyClassifier()
        result = classifier.classify(source)
        # Should be ai-agent (last in tree, but decision tree should catch both)
        assert result.content_type in (ContentType.AI_AGENT, ContentType.TOOL_REVIEW)

    def test_classify_result_output_targets(self):
        """ClassifyResult includes output_targets dict"""
        source = _make_source("bilibili_mcp_video")
        classifier = TaxonomyClassifier()
        result = classifier.classify(source)
        assert isinstance(result.output_targets, dict), \
            "output_targets should be a dict"
