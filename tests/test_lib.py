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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
