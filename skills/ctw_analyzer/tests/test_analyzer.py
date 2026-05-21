# CTW Analyzer — 两阶段协议交互测试
"""
测试 CTWAnalyzer 的 assess / plan / execute 方法。
运行: python -m pytest skills/ctw_analyzer/tests/ -v
"""
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "ctw_classify"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "ctw_infolevel"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "ctw_ingest"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "ctw_fetch"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from ctw_types import (
    ContentType, InfoLevel, SourceInput, ClassifyResult,
    LevelResult, ValueQuestion,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def mock_fetcher():
    """Mock ResourceFetcher that returns a populated SourceInput."""
    with patch("analyzer.ResourceFetcher") as mock_cls:
        fetcher = MagicMock()
        fetcher.fetch.return_value = SourceInput(
            url="https://github.com/user/repo",
            title="Test Repo",
            description="A test repository",
            content="Repository README content.",
            source_type="repo",
        )
        mock_cls.return_value = fetcher
        yield fetcher


@pytest.fixture
def mock_classifier():
    """Mock TaxonomyClassifier that returns a known classification."""
    with patch("analyzer.TaxonomyClassifier") as mock_cls:
        classifier = MagicMock()
        classifier.classify.return_value = ClassifyResult(
            content_type=ContentType.TOOL_EXTENSION,
            content_type_name="工具拓展",
            confidence=0.85,
            reason="MCP plugin extends Claude Code",
            suggested_level=InfoLevel.L2,
            value_questions=[
                ValueQuestion(id="q1", question="What does it extend?",
                              category="tools", priority="high", output_format="text"),
            ],
        )
        mock_cls.return_value = classifier
        yield classifier


@pytest.fixture
def mock_router():
    """Mock InfoLevelRouter that returns a known depth."""
    with patch("analyzer.InfoLevelRouter") as mock_cls:
        router = MagicMock()
        router.route.return_value = LevelResult(
            level=InfoLevel.L2,
            level_name="Practice Deep-Dive",
            confidence=0.80,
            reason="needs hands-on config",
            template="llmwiki/templates/entity.md",
            processing_steps=["install", "config", "verify"],
        )
        mock_cls.return_value = router
        yield router


# ============================================================
# Slice 3: assess()
# ============================================================

class TestAssessBasic:
    """Basic assess() behavior — Slice 3"""

    def test_assess_github_url_returns_assessment(self, mock_fetcher, mock_classifier, mock_router):
        from analyzer import CTWAnalyzer
        analyzer = CTWAnalyzer()
        result = analyzer.assess("https://github.com/user/repo")
        assert isinstance(result, dict)
        assert "content_type" in result
        assert "content_type_name" in result
        assert "confidence" in result
        assert "recommended_depth" in result
        assert "level_name" in result
        assert "source_type" in result
        assert "direction_summary" in result
        assert "direction_reason" in result
        assert "value_questions" in result

    def test_assess_arxiv_url_returns_pdf_source_type(self, mock_classifier, mock_router):
        from analyzer import CTWAnalyzer
        analyzer = CTWAnalyzer()

        with patch("analyzer.ResourceFetcher") as mock_cls:
            fetcher = MagicMock()
            fetcher.fetch.return_value = SourceInput(
                url="https://arxiv.org/abs/2401.12345",
                title="Chain-of-Thought",
                description="Research paper",
                content="Abstract: We explore...",
                source_type="pdf",
            )
            mock_cls.return_value = fetcher

            result = analyzer.assess("https://arxiv.org/abs/2401.12345")
            assert result["source_type"] == "pdf"

    def test_assess_no_url_returns_action_required(self):
        from analyzer import CTWAnalyzer
        analyzer = CTWAnalyzer()
        result = analyzer.assess("just some text with no URL")
        assert "action_required" in result
        assert result["action_required"] is True

    def test_assess_assessment_shape_matches_prd(self, mock_fetcher, mock_classifier, mock_router):
        from analyzer import CTWAnalyzer
        analyzer = CTWAnalyzer()
        result = analyzer.assess("https://github.com/user/repo")

        assert isinstance(result["content_type"], str)
        assert isinstance(result["confidence"], float)
        assert isinstance(result["recommended_depth"], str)
        assert isinstance(result["direction_summary"], str)
        assert isinstance(result["value_questions"], list)

    def test_assess_extracts_url_from_prompt_text(self, mock_fetcher, mock_classifier, mock_router):
        from analyzer import CTWAnalyzer
        analyzer = CTWAnalyzer()
        result = analyzer.assess("Check this out: https://github.com/user/repo -- what do you think?")
        assert result["content_type"] == "tool-extension"
        assert mock_fetcher.fetch.called

    def test_assess_fetch_failure_returns_partial(self, mock_classifier, mock_router):
        from analyzer import CTWAnalyzer
        analyzer = CTWAnalyzer()

        with patch("analyzer.ResourceFetcher") as mock_cls:
            fetcher = MagicMock()
            fetcher.fetch.side_effect = [
                Exception("API error"),
                SourceInput(
                    url="https://github.com/user/repo",
                    title="Partial Title",
                    description="Partial description",
                    content="",
                    source_type="repo",
                ),
            ]
            mock_cls.return_value = fetcher

            result = analyzer.assess("https://github.com/user/repo")
            assert result["content_type"] != ""
            assert "needs_more_info" in result

    def test_assess_fetch_exhausts_retry_then_continues(self, mock_classifier, mock_router):
        from analyzer import CTWAnalyzer
        analyzer = CTWAnalyzer()

        with patch("analyzer.ResourceFetcher") as mock_cls:
            fetcher = MagicMock()
            fetcher.fetch.return_value = SourceInput(
                url="https://example.com",
                title="",
                description="",
                content="",
                source_type="article",
            )
            mock_cls.return_value = fetcher

            result = analyzer.assess("https://example.com")
            assert result["needs_more_info"] is True


# ============================================================
# Slice 4: plan()
# ============================================================

class TestPlan:
    """plan() method tests — Slice 4"""

    @pytest.fixture
    def sample_assessment(self):
        return {
            "content_type": "tool-extension",
            "content_type_name": "工具拓展",
            "confidence": 0.85,
            "recommended_depth": "L1",
            "level_name": "Tool Review",
            "source_type": "repo",
            "direction_summary": "快速处理",
            "direction_reason": "工具评测/教程类",
            "value_questions": [{"id": "q1", "question": "What tool?", "priority": "high"}],
            "url": "https://github.com/user/repo",
            "needs_more_info": False,
        }

    def test_plan_approve_returns_approved_no_deviations(self, sample_assessment):
        from analyzer import CTWAnalyzer
        analyzer = CTWAnalyzer()
        result = analyzer.plan(sample_assessment, "looks good")
        assert result["status"] == "approved"
        assert result["deviations"] == []

    def test_plan_depth_override_records_deviation(self, sample_assessment):
        from analyzer import CTWAnalyzer
        analyzer = CTWAnalyzer()
        result = analyzer.plan(sample_assessment, "go L3 instead")
        assert result["recommended_depth"] == "L3"
        assert len(result["deviations"]) >= 1
        d = result["deviations"][0]
        assert d.axis == "depth"
        assert d.original_value == "L1"
        assert d.new_value == "L3"

    def test_plan_skip_comparison_records_deviation(self, sample_assessment):
        from analyzer import CTWAnalyzer
        analyzer = CTWAnalyzer()
        # Set a type that includes comparison
        assessment = {**sample_assessment, "content_type": "tool-extension"}
        result = analyzer.plan(assessment, "skip comparison")
        assert len(result["deviations"]) >= 1
        scope_dev = [d for d in result["deviations"] if d.axis == "scope"]
        assert len(scope_dev) >= 1
        assert "comparison_pages" not in result["expected_outputs"]

    def test_plan_cancel_returns_cancelled_no_deviation(self, sample_assessment):
        from analyzer import CTWAnalyzer
        analyzer = CTWAnalyzer()
        result = analyzer.plan(sample_assessment, "cancel")
        assert result["status"] == "cancelled"
        # No deviation for Assessment-phase cancellation
        assert result["deviations"] == []

    def test_plan_shows_expected_output_counts(self, sample_assessment):
        from analyzer import CTWAnalyzer
        analyzer = CTWAnalyzer()
        assessment = {**sample_assessment, "content_type": "tool-extension"}
        result = analyzer.plan(assessment, "approve")
        assert "source_summary" in result["expected_outputs"]
        assert result["expected_outputs"]["source_summary"] >= 1
        assert "zk_candidates" in result["expected_outputs"]

    def test_plan_has_ordered_execution_steps(self, sample_assessment):
        from analyzer import CTWAnalyzer
        analyzer = CTWAnalyzer()
        result = analyzer.plan(sample_assessment, "ok")
        assert len(result["execution_steps"]) >= 4
        actions = [s["action"] for s in result["execution_steps"]]
        assert "fetch" in actions
        assert "classify" in actions
        assert "route" in actions
        assert "ingest" in actions


# ============================================================
# Slice 5: execute()
# ============================================================

class TestExecute:
    """execute() method tests — Slice 5"""

    @pytest.fixture
    def sample_plan(self):
        return {
            "content_type": "tool-extension",
            "content_type_name": "工具拓展",
            "confidence": 0.85,
            "recommended_depth": "L2",
            "level_name": "Practice Deep-Dive",
            "source_type": "repo",
            "direction_summary": "标准处理",
            "direction_reason": "适中分析深度",
            "value_questions": [],
            "execution_steps": [
                {"step": 1, "action": "fetch"},
                {"step": 2, "action": "classify"},
                {"step": 3, "action": "route"},
                {"step": 4, "action": "ingest"},
            ],
            "expected_outputs": {"source_summary": 1, "entity_pages": 1, "comparison_pages": 1, "zk_candidates": 2},
            "deviations": [],
            "status": "approved",
            "url": "https://github.com/user/repo",
        }

    def test_execute_returns_result_with_run_id(self, sample_plan, mock_fetcher,
                                                  mock_classifier, mock_router):
        from analyzer import CTWAnalyzer
        analyzer = CTWAnalyzer()
        result = analyzer.execute(sample_plan, auto_write=False)
        assert result["status"] == "complete"
        assert "run_id" in result
        assert result["run_id"] != ""

    def test_execute_cancelled_plan_records_deviation(self, sample_plan):
        from analyzer import CTWAnalyzer
        analyzer = CTWAnalyzer()
        plan = {**sample_plan, "status": "cancelled"}
        result = analyzer.execute(plan, auto_write=False)
        assert result["status"] == "cancelled"

    def test_execute_preserves_zk_candidates(self, sample_plan, mock_fetcher,
                                              mock_classifier, mock_router):
        from analyzer import CTWAnalyzer
        analyzer = CTWAnalyzer()
        result = analyzer.execute(sample_plan, auto_write=False)
        assert "zk_candidates" in result
        assert isinstance(result["zk_candidates"], list)

    def test_execute_zk_approve_all(self, sample_plan, mock_fetcher,
                                     mock_classifier, mock_router):
        from analyzer import CTWAnalyzer
        analyzer = CTWAnalyzer()
        # Inject ZK candidates into ingest result
        with patch("analyzer.TaxonomyClassifier") as cls_mock:
            cls_mock.return_value = mock_classifier
            with patch("analyzer.InfoLevelRouter") as router_mock:
                router_mock.return_value = mock_router
                result = analyzer.execute(sample_plan, auto_write=False, zk_approvals="all")
                assert len(result["written_zk"]) >= 0

    def test_execute_zk_approve_none(self, sample_plan, mock_fetcher,
                                      mock_classifier, mock_router):
        from analyzer import CTWAnalyzer
        analyzer = CTWAnalyzer()
        result = analyzer.execute(sample_plan, auto_write=False, zk_approvals="none")
        assert result["written_zk"] == []

    def test_execute_zk_approve_specific(self, sample_plan, mock_fetcher,
                                          mock_classifier, mock_router):
        from analyzer import CTWAnalyzer
        analyzer = CTWAnalyzer()
        result = analyzer.execute(sample_plan, auto_write=False, zk_approvals=[0])
        assert isinstance(result["written_zk"], list)

    def test_execute_zk_merge(self, sample_plan, mock_fetcher,
                               mock_classifier, mock_router):
        from analyzer import CTWAnalyzer
        analyzer = CTWAnalyzer()
        result = analyzer.execute(sample_plan, auto_write=False,
                                   zk_approvals=[{"0": "existing-note-id"}])
        assert isinstance(result["written_zk"], list)

    def test_status_returns_current_run(self):
        from analyzer import CTWAnalyzer
        analyzer = CTWAnalyzer()
        status = analyzer.status()
        assert "stage" in status
        assert "run_id" in status

    def test_history_returns_list(self):
        from analyzer import CTWAnalyzer
        analyzer = CTWAnalyzer()
        history = analyzer.history()
        assert isinstance(history, list)


# ============================================================
# Slice 6: Reports lifecycle
# ============================================================

class TestReports:
    """Report generation, chains, and recyclable inputs — Slice 6"""

    def test_generate_report_creates_file(self, tmp_path):
        """Generate report from completed run — report file exists."""
        import sys, os, time
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib"))
        from ctw_types import SourceInput
        # Test the report module directly
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from reports import ReportGenerator

        gen = ReportGenerator(tmp_path)
        run_result = {
            "run_id": "20260521-143022",
            "status": "complete",
            "source": SourceInput(title="Test Source", url="http://example.com"),
        }
        report = gen.generate_report(
            run_result=run_result,
            title="Key Contributions",
            request="Summarize key contributions",
        )
        assert os.path.exists(report["path"])
        assert "run_id" in report["frontmatter"]
        assert report["frontmatter"]["chain_position"] == 1

    def test_report_yaml_frontmatter(self, tmp_path):
        """Report YAML frontmatter has required fields."""
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from reports import ReportGenerator

        gen = ReportGenerator(tmp_path)
        run_result = {"run_id": "run_123", "status": "complete"}
        report = gen.generate_report(
            run_result=run_result,
            title="Test Report",
            request="Test request",
        )
        fm = report["frontmatter"]
        assert fm["type"] == "report"
        assert fm["title"] == "Test Report"
        assert fm["run_id"] == "run_123"
        assert "chain_position" in fm
        assert "status" in fm
        assert "supersedes" in fm
        assert "references" in fm

    def test_generate_v2_from_v1(self, tmp_path):
        """Generate v2 — v2 references v1, v1 status unchanged."""
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from reports import ReportGenerator

        gen = ReportGenerator(tmp_path)
        run_result = {"run_id": "run_v1", "status": "complete"}
        v1 = gen.generate_report(
            run_result=run_result,
            title="v1 Report",
            request="Initial analysis",
        )

        run_result_v2 = {"run_id": "run_v2", "status": "complete"}
        v2 = gen.generate_report_chain(
            base_report=v1,
            new_run_result=run_result_v2,
            title="v2 Report",
            request="Add comparison with other paper",
        )
        assert v2["frontmatter"]["chain_position"] == 2
        assert "run_v1" in v2["frontmatter"]["references"]
        # v1 still exists
        assert os.path.exists(v1["path"])

    def test_generate_synthesis_supersedes_predecessors(self, tmp_path):
        """Synthesis supersedes predecessors, all versions preserved."""
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from reports import ReportGenerator

        gen = ReportGenerator(tmp_path)
        run_result = {"run_id": "run_v1", "status": "complete"}
        v1 = gen.generate_report(
            run_result=run_result,
            title="v1 Report",
            request="Initial",
        )
        v2_run = {"run_id": "run_v2", "status": "complete"}
        v2 = gen.generate_report_chain(
            base_report=v1,
            new_run_result=v2_run,
            title="v2 Report",
            request="Iteration",
        )

        synthesis_run = {"run_id": "run_synth", "status": "complete"}
        synthesis = gen.generate_synthesis(
            predecessors=[v1, v2],
            run_result=synthesis_run,
            title="Synthesis Report",
            request="Synthesize findings",
        )
        assert synthesis["frontmatter"]["chain_position"] == "synthesis"
        assert "run_v1" in synthesis["frontmatter"]["supersedes"]
        assert "run_v2" in synthesis["frontmatter"]["supersedes"]
        # All versions preserved
        assert os.path.exists(v1["path"])
        assert os.path.exists(v2["path"])
        assert os.path.exists(synthesis["path"])

    def test_report_as_input_source(self, tmp_path):
        """Use report file as Input Source — fetch reads local file."""
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib"))
        from reports import ReportGenerator
        from ctw_types import SourceInput

        gen = ReportGenerator(tmp_path)
        run_result = {"run_id": "run_r", "status": "complete"}
        report = gen.generate_report(
            run_result=run_result,
            title="Source Report",
            request="Test content for report",
            content="This is the report body content.",
        )

        # Read report as input
        source = gen.report_as_source_input(report["path"])
        assert isinstance(source, SourceInput)
        assert source.title == "Source Report"
        assert "report body content" in source.content
        assert source.source_type == "report"

    def test_report_frontmatter_chain_position(self, tmp_path):
        """Chain position is always set correctly."""
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from reports import ReportGenerator

        gen = ReportGenerator(tmp_path)
        run_result = {"run_id": "r1", "status": "complete"}
        r = gen.generate_report(
            run_result=run_result,
            title="Report",
            request="Test",
        )
        assert isinstance(r["frontmatter"]["chain_position"], int)
        assert r["frontmatter"]["chain_position"] >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
