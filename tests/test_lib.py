# CTW Implement — lib 层单元测试
"""
共享库的单元测试。
运行: python -m pytest tests\test_lib.py -v
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import pytest
from ctw_types import (
    ContentType, InfoLevel, GateStatus, GateName,
    SourceInput, ClassifyResult, LevelResult,
    ValueQuestion, ZkCandidate, PipelineResult
)


class TestContentType:
    """ContentType 枚举测试"""

    def test_all_types_from_yaml_exist(self):
        """验证 10 种类型 + unknown 都被定义"""
        assert ContentType.TOOL_EXTENSION.value == "tool-extension"
        assert ContentType.TOOL_REVIEW.value == "tool-review"
        assert ContentType.PRACTICE_TUTORIAL.value == "practice-tutorial"
        assert ContentType.ARCHITECTURE_ANALYSIS.value == "architecture-analysis"
        assert ContentType.PAPER_REVIEW.value == "paper-review"
        assert ContentType.TECH_NEWS.value == "tech-news"
        assert ContentType.EXPERIENCE_SHARE.value == "experience-share"
        assert ContentType.SPEC_STANDARD.value == "spec-standard"
        assert ContentType.SECURITY_RESEARCH.value == "security-research"
        assert ContentType.AI_AGENT.value == "ai-agent"
        assert ContentType.UNKNOWN.value == "unknown"
        assert len(ContentType) == 11

    def test_from_string(self):
        assert ContentType("tool-extension") == ContentType.TOOL_EXTENSION
        assert ContentType("unknown") == ContentType.UNKNOWN
        with pytest.raises(ValueError):
            ContentType("nonexistent")


class TestInfoLevel:
    """InfoLevel 枚举测试"""

    def test_levels_ordered(self):
        levels = list(InfoLevel)
        assert levels == [InfoLevel.L0, InfoLevel.L1, InfoLevel.L2, InfoLevel.L3, InfoLevel.L4]

    def test_comparison(self):
        assert InfoLevel.L0.value == "L0"
        assert InfoLevel.L4.value == "L4"


class TestGateEnums:
    """Gate 相关枚举测试"""

    def test_gate_names_v2(self):
        """验证 v2.0 gate 名称与 gates.yaml 一致"""
        names = {g.value for g in GateName}
        assert "CLASSIFY" in names
        assert "APPROVE_OUTPUT" in names
        assert "APPROVE_ZK" in names
        assert "RESOLVE_CONFLICT" in names
        assert "PROMOTE" in names
        assert "CONFIG_CHANGE" in names
        assert len(GateName) == 6

    def test_gate_status(self):
        assert GateStatus.PASSED.value == "passed"
        assert GateStatus.PENDING.value == "pending"
        assert GateStatus.PENDING_MODIFIED.value == "pending_modified"


class TestSourceInput:
    """SourceInput 数据类测试"""

    def test_default_construction(self):
        s = SourceInput()
        assert s.url == ""
        assert s.title == ""
        assert s.content == ""

    def test_video_source(self):
        s = SourceInput(
            url="https://www.bilibili.com/video/BV12345",
            title="MCP FileSystem Server",
            description="Claude Code 文件系统插件教程",
            source_type="video"
        )
        assert s.source_type == "video"
        assert "bilibili" in s.url

    def test_repo_source(self):
        s = SourceInput(
            url="https://github.com/PrefectHQ/prefect",
            title="Prefect",
            source_type="repo"
        )
        assert s.source_type == "repo"


class TestClassifyResult:
    """ClassifyResult 数据类测试"""

    def test_default(self):
        r = ClassifyResult()
        assert r.content_type == ContentType.UNKNOWN
        assert r.confidence == 0.0
        assert r.suggested_level == InfoLevel.L1

    def test_with_values(self):
        r = ClassifyResult(
            content_type=ContentType.TOOL_EXTENSION,
            content_type_name="工具拓展",
            confidence=0.85,
            reason="B站视频介绍 MCP 插件 → 已有工具的扩展",
            suggested_level=InfoLevel.L2
        )
        assert r.confidence == 0.85
        assert r.suggested_level == InfoLevel.L2


class TestZkCandidate:
    """ZkCandidate 数据类测试"""

    def test_default_priority(self):
        c = ZkCandidate(id="1", title="Test", abstract="A test note")
        assert c.priority == 3
        assert c.status == "pending"

    def test_merge_target(self):
        c = ZkCandidate(
            id="2", title="Git Safety",
            abstract="AI should commit before write",
            merge_target="git-rollback-as-safety-net.md"
        )
        assert c.merge_target is not None


class TestPipelineResult:
    """PipelineResult 数据类测试"""

    def test_initial_status(self):
        r = PipelineResult(source=SourceInput(title="Test"))
        assert r.status == "init"
        assert r.classify is None
        assert r.errors == []

    def test_with_results(self):
        r = PipelineResult(
            source=SourceInput(title="Test"),
            classify=ClassifyResult(content_type=ContentType.PAPER_REVIEW, confidence=0.9),
            status="processing"
        )
        assert r.classify is not None
        assert r.classify.content_type == ContentType.PAPER_REVIEW
        assert r.status == "processing"


class TestValueQuestion:
    """ValueQuestion 数据类测试"""

    def test_skip_condition(self):
        q = ValueQuestion(
            id="fresh_deploy",
            question="部署步骤？",
            category="部署指南",
            priority="critical",
            output_format="分步指南",
            skip_condition="current_config 返回非空"
        )
        assert q.skip_condition is not None

    def test_no_skip(self):
        q = ValueQuestion(
            id="current_config",
            question="本地配置？",
            category="环境评估",
            priority="critical",
            output_format="状态"
        )
        assert q.skip_condition is None


class TestProcessingPlan:
    """ProcessingPlan dataclass tests — Slice 1"""

    def test_default_construction(self):
        from ctw_types import ProcessingPlan
        p = ProcessingPlan()
        assert p.status == "proposed"
        assert p.content_type_name == ""
        assert p.confidence == 0.0
        assert p.recommended_depth == ""
        assert p.direction_summary == ""
        assert p.execution_steps == []
        assert p.deviations == []
        assert p.expected_outputs == {}

    def test_with_assessment(self):
        from ctw_types import ProcessingPlan, WorkflowDeviation
        p = ProcessingPlan(
            content_type_name="工具拓展",
            content_type="tool-extension",
            confidence=0.85,
            recommended_depth="L2",
            level_name="Practice Deep-Dive",
            source_type="repo",
            direction_summary="Go deep on this tool extension",
            direction_reason="MCP plugin extends Claude Code",
            value_questions=["current_config"],
            execution_steps=[
                {"step": 1, "action": "fetch", "description": "Fetch GitHub repo"},
                {"step": 2, "action": "classify", "description": "Classify content type"},
                {"step": 3, "action": "route", "description": "Route to depth L2"},
                {"step": 4, "action": "ingest", "description": "Generate wiki + ZK"},
            ],
            expected_outputs={
                "source_summary": 1,
                "entity_pages": 1,
                "comparison_pages": 1,
                "zk_candidates": 2,
            },
            deviations=[WorkflowDeviation(
                axis="depth",
                original_value="L1",
                new_value="L2",
                reason="Human override for deeper analysis",
            )],
            status="approved",
        )
        assert p.content_type_name == "工具拓展"
        assert p.status == "approved"
        assert len(p.execution_steps) == 4
        assert p.expected_outputs["source_summary"] == 1
        assert len(p.deviations) == 1
        assert p.deviations[0].axis == "depth"

    def test_lifecycle_states_valid(self):
        from ctw_types import ProcessingPlan
        valid_states = {"proposed", "approved", "in_progress", "complete", "cancelled"}
        for state in valid_states:
            p = ProcessingPlan(status=state)
            assert p.status == state

    def test_default_execution_steps_empty(self):
        from ctw_types import ProcessingPlan
        p = ProcessingPlan()
        assert isinstance(p.execution_steps, list)
        assert len(p.execution_steps) == 0


class TestWorkflowDeviation:
    """WorkflowDeviation dataclass tests — Slice 1"""

    def test_default_construction(self):
        from ctw_types import WorkflowDeviation
        d = WorkflowDeviation()
        assert d.axis == ""
        assert d.original_value == ""
        assert d.new_value == ""
        assert d.reason == ""
        assert d.timestamp != ""
        assert d.run_id == ""

    def test_depth_override_deviation(self):
        from ctw_types import WorkflowDeviation
        d = WorkflowDeviation(
            axis="depth",
            original_value="L1",
            new_value="L3",
            reason="Repo too complex for quick scan",
            run_id="run_123",
        )
        assert d.axis == "depth"
        assert d.original_value == "L1"
        assert d.new_value == "L3"
        assert d.reason == "Repo too complex for quick scan"
        assert d.run_id == "run_123"
        assert isinstance(d.timestamp, str)
        assert len(d.timestamp) == 14  # YYYYMMDDHHmmss

    def test_type_override_deviation(self):
        from ctw_types import WorkflowDeviation
        d = WorkflowDeviation(
            axis="type",
            original_value="tech-news",
            new_value="tool-review",
            reason="This is actually reviewing a tool",
        )
        assert d.axis == "type"

    def test_scope_override_deviation(self):
        from ctw_types import WorkflowDeviation
        d = WorkflowDeviation(
            axis="scope",
            original_value="full",
            new_value="skip_comparison",
            reason="Don't need comparison for this",
        )
        assert d.axis == "scope"

    def test_cancellation_deviation(self):
        from ctw_types import WorkflowDeviation
        d = WorkflowDeviation(
            axis="cancellation",
            original_value="in_progress",
            new_value="cancelled",
            reason="Changed my mind mid-execution",
        )
        assert d.axis == "cancellation"

    def test_timestamp_auto_generated(self):
        from ctw_types import WorkflowDeviation
        d = WorkflowDeviation(axis="type", original_value="a", new_value="b")
        assert d.timestamp != ""
        assert len(d.timestamp) == 14
        assert d.timestamp.isdigit()


class TestZkCandidateIdFormat:
    """ZK candidate timestamp ID format test — Slice 1"""

    def test_id_is_timestamp_format(self):
        """ZK candidate IDs should use YYYYMMDDHHmmss format."""
        from ctw_types import ZkCandidate
        import re
        c = ZkCandidate(title="Test Note", abstract="Test content")
        # The default factory should produce a timestamp ID
        assert c.id != ""
        assert re.match(r"^\d{14}$", c.id), (
            f"Expected timestamp ID (YYYYMMDDHHmmss), got: {c.id}"
        )

    def test_multiple_candidates_separated_by_second_have_unique_ids(self):
        """ZK candidates created in different seconds get unique timestamp IDs."""
        from ctw_types import ZkCandidate
        import time
        c1 = ZkCandidate(title="Note 1", abstract="Content 1")
        time.sleep(1.1)  # Cross second boundary
        c2 = ZkCandidate(title="Note 2", abstract="Content 2")
        assert c1.id != c2.id, "ZK candidate IDs should be unique when created in different seconds"


class TestPipelineResultLifecycle:
    """PipelineResult lifecycle states — Slice 1"""

    def test_default_status_init(self):
        from ctw_types import PipelineResult, SourceInput
        r = PipelineResult(source=SourceInput())
        assert r.status == "init"

    def test_full_lifecycle(self):
        from ctw_types import PipelineResult, SourceInput
        states = ["proposed", "approved", "in_progress", "complete", "cancelled"]
        for state in states:
            r = PipelineResult(source=SourceInput(), status=state)
            assert r.status == state

    def test_transition_from_proposed_to_approved(self):
        from ctw_types import PipelineResult, SourceInput
        r = PipelineResult(source=SourceInput(), status="proposed")
        assert r.status == "proposed"
        r.status = "approved"
        assert r.status == "approved"

    def test_cancelled_state(self):
        from ctw_types import PipelineResult, SourceInput
        r = PipelineResult(source=SourceInput(), status="cancelled")
        assert r.status == "cancelled"


# ============================================================
# Slice 2: Output paths + template wiring tests
# ============================================================

class TestZKOutputPath:
    """ZK output path to zettelkasten/2-permanent/ — Slice 2"""

    def test_get_output_path_zk_returns_zettelkasten_path(self, tmp_path):
        """get_output_path('zk') returns .../zettelkasten/2-permanent/"""
        from unittest.mock import patch
        from ctw_config import CTWConfig
        config = CTWConfig()
        repo = str(tmp_path / "repo")
        with patch.object(config, "_save_settings"):
            config.set_repository(repo)
        path = config.get_output_path("zk")
        assert "zettelkasten" in str(path)
        assert "2-permanent" in str(path)
        assert str(path).endswith("2-permanent")

    def test_get_output_path_sources_still_works(self, tmp_path):
        """get_output_path('sources') still returns wiki/sources"""
        from unittest.mock import patch
        from ctw_config import CTWConfig
        config = CTWConfig()
        repo = str(tmp_path / "repo")
        with patch.object(config, "_save_settings"):
            config.set_repository(repo)
        path = config.get_output_path("sources")
        assert "wiki" in str(path)
        assert "sources" in str(path)

    def test_write_outputs_creates_zettelkasten_dir(self, tmp_path):
        """write_outputs() creates zettelkasten/2-permanent/ not zk/"""
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "ctw_ingest"))
        from ctw_config import CTWConfig
        from ctw_types import SourceInput, ClassifyResult, ContentType, LevelResult, IngestResult
        from ingest import LLMWikiIngest

        config = CTWConfig()
        repo = str(tmp_path / "artifact_repo")
        # Bypass set_repository — we don't want _save_settings() to corrupt
        # the real config/settings.yaml with a temp path that won't survive.
        os.makedirs(repo, exist_ok=True)
        from pathlib import Path
        config._repository_path = Path(repo).resolve()
        ingest = LLMWikiIngest(config=config)

        result = IngestResult()
        result.source_summary = "test summary"
        result.output_files = [
            str(tmp_path / "artifact_repo" / "wiki" / "sources" / "test.md"),
            str(tmp_path / "artifact_repo" / "zettelkasten" / "2-permanent" / "20260521143022.md"),
        ]
        result.zk_candidates = ["Test Candidate"]

        written = ingest.write_outputs(result)
        zk_dir = os.path.join(repo, "zettelkasten", "2-permanent")
        assert os.path.isdir(zk_dir), f"Expected {zk_dir} to exist"
        assert not os.path.isdir(os.path.join(repo, "zk")), "Old zk/ dir should not exist"


class TestIngestTemplateWiring:
    """Ingest uses TemplateEngine instead of inlined templates — Slice 2"""

    def test_ingest_passes_value_questions_to_source_summary(self):
        """Value questions from ClassifyResult appear in source summary output."""
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "ctw_ingest"))
        from ctw_types import (
            SourceInput, ClassifyResult, ContentType, InfoLevel, LevelResult, ValueQuestion
        )
        from ingest import LLMWikiIngest

        source = SourceInput(
            url="https://example.com",
            title="Test Article",
            content="Some test content about tools.",
            source_type="article",
        )
        classify = ClassifyResult(
            content_type=ContentType.PRACTICE_TUTORIAL,
            content_type_name="实践教程",
            confidence=0.9,
            value_questions=[
                ValueQuestion(id="q1", question="What tool?", category="tools",
                              priority="high", output_format="text"),
                ValueQuestion(id="q2", question="How to use?", category="usage",
                              priority="critical", output_format="text"),
            ],
        )
        level = LevelResult(level=InfoLevel.L1, level_name="Tool Review")

        ingest = LLMWikiIngest()
        summary = ingest.generate_source_summary(source, classify_result=classify)
        assert "What tool?" in summary, "Value questions should appear in source summary"

    def test_ingest_uses_template_engine_not_inline(self):
        """Ingest methods call TemplateEngine.render() instead of inline string formatting."""
        import sys, os
        from unittest.mock import patch, MagicMock
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "ctw_ingest"))
        from ctw_types import (
            SourceInput, ClassifyResult, ContentType, InfoLevel, LevelResult, ValueQuestion
        )
        from ingest import LLMWikiIngest

        with patch("ingest.TemplateEngine") as mock_engine_cls:
            mock_engine = MagicMock()
            mock_engine.read_template.return_value = "# {{title}}\n\n{{source_type}}"
            mock_engine.render.return_value = "Rendered content"
            mock_engine_cls.return_value = mock_engine

            ingest = LLMWikiIngest()
            source = SourceInput(title="Test", url="http://x.com", content="Content",
                                source_type="article")

            result = ingest.ingest(
                source,
                ClassifyResult(content_type=ContentType.TOOL_EXTENSION,
                              content_type_name="工具拓展", confidence=0.85,
                              value_questions=[
                                  ValueQuestion(id="q1", question="Q?",
                                               category="test", priority="high",
                                               output_format="text")
                              ]),
                LevelResult(level=InfoLevel.L2, level_name="Practice Deep-Dive"),
            )

            assert mock_engine.read_template.called, (
                "TemplateEngine.read_template should be called"
            )
            assert mock_engine.render.called, (
                "TemplateEngine.render should be called"
            )


class TestTemplateEngineAgentWorkspace:
    """TemplateEngine reads from agent workspace — Slice 2"""

    def test_template_dir_points_to_agent_workspace(self):
        from ctw_templates import TemplateEngine
        engine = TemplateEngine()
        assert "agents" in str(engine.template_dir)
        assert "ips-agent" in str(engine.template_dir)
        assert "templates" in str(engine.template_dir)
        assert "llmwiki" in str(engine.template_dir)

    def test_template_substitution(self):
        """TemplateEngine substitutes {{var}} placeholders with data values."""
        from ctw_templates import TemplateEngine
        engine = TemplateEngine()
        template = "# {{title}}\n\nAuthor: {{author}}\n\n## Summary\n{{summary}}"
        data = {"title": "Test", "author": "John", "summary": "A test summary"}
        result = engine.render(template, data)
        assert "Test" in result
        assert "John" in result
        assert "A test summary" in result
        assert "{{title}}" not in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
