# CTW Pipeline — 集成测试
"""
测试 CTWPipeline 的完整管线编排功能，验证三阶段串联正确性。
运行: python -m pytest skills/ctw_pipeline/tests/ -v
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "ctw_classify"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "ctw_infolevel"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "ctw_ingest"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from ctw_types import (
    ContentType, InfoLevel, SourceInput, ClassifyResult,
    LevelResult, PipelineResult, GateTrigger, GateName, GateStatus,
)
from pipeline import CTWPipeline, run_pipeline


@pytest.fixture
def pipeline():
    return CTWPipeline()


@pytest.fixture
def tool_extension_source():
    return SourceInput(
        url="https://github.com/modelcontextprotocol/servers",
        title="MCP FileSystem Server",
        description="MCP plugin extending Claude Code with filesystem access",
        content="## Install\nnpm install @modelcontextprotocol/server-filesystem\n## Config\n...",
        source_type="article",
    )


@pytest.fixture
def paper_source():
    return SourceInput(
        url="https://arxiv.org/abs/2401.12345",
        title="Chain-of-Thought Prompting",
        description="Research paper on reasoning in LLMs",
        content="## Abstract\nChain-of-thought prompting improves reasoning by generating intermediate steps...",
        source_type="pdf",
    )


# ============================================================
# Integration Tests
# ============================================================

class TestPipelineIntegration:
    """全管线集成测试"""

    def test_full_pipeline_tool_extension(self, pipeline, tool_extension_source):
        result = pipeline.run(tool_extension_source)
        assert isinstance(result, PipelineResult)
        assert result.classify is not None
        assert result.level is not None
        assert result.ingest is not None
        assert result.classify.content_type in (
            ContentType.TOOL_EXTENSION, ContentType.AI_AGENT, ContentType.UNKNOWN
        )
        assert result.level.level in (
            InfoLevel.L1, InfoLevel.L2, InfoLevel.L3, InfoLevel.L4, InfoLevel.L0
        )
        assert len(result.ingest.output_files) >= 1

    def test_full_pipeline_paper(self, pipeline, paper_source):
        result = pipeline.run(paper_source)
        assert result.classify is not None
        assert result.classify.content_type in (
            ContentType.PAPER_REVIEW, ContentType.UNKNOWN
        )

    def test_pipeline_with_override(self, pipeline, tool_extension_source):
        """测试手动覆盖分类和路由"""
        override_classify = ClassifyResult(
            content_type=ContentType.ARCHITECTURE_ANALYSIS,
            content_type_name="架构分析",
            confidence=1.0,
        )
        override_level = LevelResult(
            level=InfoLevel.L4,
            level_name="Research Synthesis",
        )
        result = pipeline.run(
            tool_extension_source,
            classify_override=override_classify,
            level_override=override_level,
        )
        assert result.classify.content_type == ContentType.ARCHITECTURE_ANALYSIS
        assert result.level.level == InfoLevel.L4

    def test_pipeline_status(self, pipeline, tool_extension_source):
        result = pipeline.run(tool_extension_source)
        assert result.status in ("complete", "waiting_human")

    def test_pipeline_gates_triggered(self, pipeline, tool_extension_source):
        result = pipeline.run(tool_extension_source)
        assert len(result.gates_triggered) >= 1
        classify_gates = [g for g in result.gates_triggered if g.gate == GateName.CLASSIFY]
        assert len(classify_gates) == 1
        assert classify_gates[0].status == GateStatus.PASSED

    def test_pipeline_zk_notes_extracted(self, pipeline):
        source = SourceInput(
            url="https://example.com",
            title="Test Source",
            content="## ZK Atomic Candidates\n\n- [ ] Note about workflow idempotence\n- [ ] Note about tool composition\n",
            source_type="article",
        )
        result = pipeline.run(source)
        assert len(result.zk_notes) >= 1

    def test_convenience_run_pipeline(self):
        result = run_pipeline({
            "url": "https://example.com",
            "title": "Quick Test",
            "content": "A simple test source with some content about AI agents and automation.",
            "source_type": "article",
        })
        assert isinstance(result, PipelineResult)
        assert result.classify is not None


class TestPipelineEmptyInput:
    """边界情况：空输入"""

    def test_empty_source(self, pipeline):
        source = SourceInput()
        result = pipeline.run(source)
        assert result.status in ("complete", "waiting_human")
        assert result.classify is not None
        assert result.classify.content_type == ContentType.UNKNOWN

    def test_no_content(self, pipeline):
        source = SourceInput(url="https://example.com", title="No Content")
        result = pipeline.run(source)
        assert result.status == "waiting_human"
        assert result.ingest.human_feedback_required is True


class TestPipelineConfig:
    """配置测试"""

    def test_pipeline_status_summary(self, pipeline):
        status = pipeline.status()
        assert "classifier" in status
        assert "router" in status
        assert "ingest" in status

    def test_custom_project_path(self):
        pipeline = CTWPipeline(project_path=r"D:\MainWorkSpace\contextToWhatend")
        assert "contextToWhatend" in str(pipeline.config.project_path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
