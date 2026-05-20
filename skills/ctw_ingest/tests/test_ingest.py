# CTW Ingest — LLM Wiki Ingest Skill 单元测试
"""
测试 LLMWikiIngest 的所有核心功能。
运行: python -m pytest tests/ -v
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from ctw_types import (
    ContentType, InfoLevel, SourceInput, ClassifyResult,
    LevelResult, IngestResult, ZkCandidate, ValueQuestion,
)
from ingest import LLMWikiIngest


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def ingest():
    return LLMWikiIngest()


@pytest.fixture
def tool_extension_source():
    return SourceInput(
        url="https://github.com/modelcontextprotocol/servers",
        title="MCP FileSystem Server - Claude Code Plugin",
        description="How to use MCP FileSystem Server with Claude Code",
        content="## Install\nnpm install -g @modelcontextprotocol/server-filesystem\n## Config\nEdit claude_desktop_config.json...",
        source_type="article",
        raw_file_path="articles/2024/mcp-filesystem-server.md",
    )


@pytest.fixture
def tool_extension_classify():
    return ClassifyResult(
        content_type=ContentType.TOOL_EXTENSION,
        content_type_name="工具拓展",
        confidence=0.85,
        reason="MCP plugin extends Claude Code",
        suggested_level=InfoLevel.L2,
        value_questions=[
            ValueQuestion(
                id="current_config", question="current config?",
                category="env", priority="critical", output_format="state",
            ),
        ],
        output_targets={"entity": True, "comparison": True},
    )


@pytest.fixture
def tool_extension_level():
    return LevelResult(
        level=InfoLevel.L2,
        level_name="Practice Deep-Dive",
        confidence=0.80,
        reason="needs hands-on config",
        template="llmwiki/templates/entity.md",
        processing_steps=["install", "config", "verify"],
    )


@pytest.fixture
def practice_tutorial_source():
    return SourceInput(
        url="https://www.bilibili.com/video/BV12345",
        title="n8n Workflow Automation",
        description="Learn n8n from scratch",
        content="n8n is an open-source automation tool...",
        source_type="video",
    )


@pytest.fixture
def practice_tutorial_classify():
    return ClassifyResult(
        content_type=ContentType.PRACTICE_TUTORIAL,
        content_type_name="实践教程",
        confidence=0.90,
        reason="video tutorial",
        suggested_level=InfoLevel.L1,
    )


@pytest.fixture
def architecture_source():
    return SourceInput(
        url="https://example.com/architecture",
        title="OpenClaw Gateway Architecture",
        description="Deep dive into OpenClaw gateway architecture",
        content="## Overview\nOpenClaw uses layered architecture...\n## Entities\n### Gateway Engine\n### Plugin System\n### Session Manager",
        source_type="article",
    )


@pytest.fixture
def architecture_classify():
    return ClassifyResult(
        content_type=ContentType.ARCHITECTURE_ANALYSIS,
        content_type_name="架构分析",
        confidence=0.88,
        reason="system architecture deep dive",
        suggested_level=InfoLevel.L3,
        value_questions=[],
        output_targets={"entity": True, "concept": True, "comparison": True},
    )


@pytest.fixture
def paper_review_source():
    return SourceInput(
        url="https://arxiv.org/abs/2401.12345",
        title="Chain-of-Thought Prompting Elicits Reasoning",
        description="LLM reasoning research paper",
        content="## Abstract\nWe explore how generating a chain of thought...",
        source_type="pdf",
    )


@pytest.fixture
def paper_review_classify():
    return ClassifyResult(
        content_type=ContentType.PAPER_REVIEW,
        content_type_name="论文评审",
        confidence=0.92,
        reason="academic paper",
        suggested_level=InfoLevel.L4,
    )


# ============================================================
# Test Cases
# ============================================================

class TestIngestToolExtension:
    """工具拓展类型 → entity + comparison + zk"""

    def test_ingest_tool_extension(self, ingest, tool_extension_source,
                                    tool_extension_classify, tool_extension_level):
        result = ingest.ingest(
            tool_extension_source,
            tool_extension_classify,
            tool_extension_level,
        )
        assert isinstance(result, IngestResult)
        assert len(result.entity_pages) >= 1
        assert len(result.comparison_pages) >= 1
        assert len(result.zk_candidates) >= 1


class TestIngestPracticeTutorial:
    """实践教程 → source-summary + zk"""

    def test_ingest_practice_tutorial(self, ingest, practice_tutorial_source,
                                       practice_tutorial_classify):
        result = ingest.ingest(
            practice_tutorial_source,
            practice_tutorial_classify,
            LevelResult(level=InfoLevel.L1, level_name="Tool Review"),
        )
        assert isinstance(result, IngestResult)
        assert result.source_summary != ""
        assert len(result.zk_candidates) >= 1


class TestIngestArchitectureAnalysis:
    """架构分析 → entity + concepts + comparison"""

    def test_ingest_architecture_analysis(self, ingest, architecture_source,
                                           architecture_classify):
        result = ingest.ingest(
            architecture_source,
            architecture_classify,
            LevelResult(level=InfoLevel.L3, level_name="System Analysis"),
        )
        assert isinstance(result, IngestResult)
        assert len(result.entity_pages) >= 1
        assert len(result.concept_pages) >= 1
        assert len(result.comparison_pages) >= 1


class TestIngestPaperReview:
    """论文评审 → source-summary + concepts + zk"""

    def test_ingest_paper_review(self, ingest, paper_review_source,
                                  paper_review_classify):
        result = ingest.ingest(
            paper_review_source,
            paper_review_classify,
            LevelResult(level=InfoLevel.L4, level_name="Research Synthesis"),
        )
        assert isinstance(result, IngestResult)
        assert result.source_summary != ""
        assert len(result.concept_pages) >= 1
        assert len(result.zk_candidates) >= 1


class TestExtractZkCandidates:
    """ZK candidates extraction"""

    def test_extract_zk_candidates_from_text(self, ingest):
        md = """## ZK Atomic Candidates

- [ ] AI should backup before commit
- [ ] Workflows should be idempotent
- [ ] Tool composition beats monolithic tools

## Other Content

Some unrelated content."""
        candidates = ingest.extract_zk_candidates(md, min_confidence=0.5)
        assert len(candidates) >= 1
        for c in candidates:
            assert isinstance(c, ZkCandidate)
            assert c.confidence >= 0.5

    def test_confidence_filter(self, ingest):
        md = """## ZK Atomic Candidates

- [ ] High-value candidate A
- [ ] Low-value candidate B"""
        all_candidates = ingest.extract_zk_candidates(md, min_confidence=0.0)
        filtered = ingest.extract_zk_candidates(md, min_confidence=0.9)
        assert len(all_candidates) >= 1
        # Filtered should be <= all since some may be below threshold
        assert len(filtered) <= len(all_candidates)


class TestSourceSummary:
    """Source summary output tests"""

    def test_source_summary_renders_frontmatter(self, ingest, practice_tutorial_source):
        summary = ingest.generate_source_summary(practice_tutorial_source)
        assert summary.startswith("---")
        assert "type:" in summary
        assert "source-summary" in summary
        assert "title:" in summary

    def test_source_summary_includes_claims(self, ingest, tool_extension_source):
        summary = ingest.generate_source_summary(tool_extension_source)
        assert "核心论点" in summary or "Claims" in summary


class TestEntityPage:
    """Entity page tests"""

    def test_entity_page_has_required_fields(self, ingest):
        data = {
            "name": "MCP Server",
            "type": "tool",
            "version": "1.0.0",
            "license": "MIT",
            "description": "Model Context Protocol Server",
        }
        page = ingest.generate_entity_page("MCP Server", data)
        assert page != ""
        assert "MCP Server" in page
        assert "type" in page.lower() or "类型" in page


class TestComparisonPage:
    """Comparison page v2.0 — recommendation field"""

    def test_comparison_page_has_recommendation(self, ingest):
        result = ingest.ingest(
            SourceInput(
                url="https://example.com",
                title="MCP vs HTTP API",
                content="Comparing MCP and HTTP API...",
                source_type="article",
            ),
            ClassifyResult(
                content_type=ContentType.TOOL_EXTENSION,
                content_type_name="工具拓展",
                confidence=0.8,
            ),
            LevelResult(level=InfoLevel.L2),
        )
        if result.comparison_pages:
            found_rec = any(
                "recommendation" in p.lower() or "推荐" in p
                for p in result.comparison_pages
            )
            assert found_rec, "comparison should include recommendation info"


class TestIngestResult:
    """IngestResult output tracking"""

    def test_ingest_result_has_output_files(self, ingest, tool_extension_source,
                                              tool_extension_classify, tool_extension_level):
        result = ingest.ingest(
            tool_extension_source,
            tool_extension_classify,
            tool_extension_level,
        )
        assert len(result.output_files) >= 1
        for f in result.output_files:
            assert f != ""
            # Path should be absolute (repo set) or empty (repo not set)
            assert os.path.isabs(f) or f == ""

    def test_empty_source_handled(self, ingest):
        """empty/missing content handled gracefully"""
        empty_source = SourceInput(
            url="",
            title="",
            content="",
            source_type="",
        )
        result = ingest.ingest(
            empty_source,
            ClassifyResult(content_type=ContentType.UNKNOWN),
            LevelResult(level=InfoLevel.L0),
        )
        assert isinstance(result, IngestResult)
        # Should not crash; either marks human feedback or returns empty
        assert isinstance(result.human_feedback_required, bool)


class TestShouldGenerateComparison:
    """Comparison generation routing"""

    def test_tool_extension_needs_comparison(self, ingest):
        cr = ClassifyResult(content_type=ContentType.TOOL_EXTENSION)
        assert ingest.should_generate_comparison(cr) is True

    def test_practice_tutorial_no_comparison(self, ingest):
        cr = ClassifyResult(content_type=ContentType.PRACTICE_TUTORIAL)
        assert ingest.should_generate_comparison(cr) is False

    def test_architecture_needs_comparison(self, ingest):
        cr = ClassifyResult(content_type=ContentType.ARCHITECTURE_ANALYSIS)
        assert ingest.should_generate_comparison(cr) is True

    def test_paper_review_no_comparison(self, ingest):
        cr = ClassifyResult(content_type=ContentType.PAPER_REVIEW)
        assert ingest.should_generate_comparison(cr) is False

    def test_unknown_no_comparison(self, ingest):
        cr = ClassifyResult(content_type=ContentType.UNKNOWN)
        assert ingest.should_generate_comparison(cr) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
