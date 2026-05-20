# CTW Analyzer — 智能交互入口测试
"""
测试 CTWAnalyzer 的智能分析协议：URL提取、自动分诊、深度决策、进度反馈、追加机制。
"""
import sys
import os
import json
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "ctw_classify"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "ctw_infolevel"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "ctw_ingest"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "ctw_pipeline"))

from ctw_types import (
    ContentType, InfoLevel, SourceInput, ClassifyResult,
    LevelResult, PipelineResult,
)
from analyzer import (
    CTWAnalyzer, ctw_ana, AnalysisResult, AnalyzedSource, AnalysisProgress,
    extract_urls, infer_source_type, extract_title_from_prompt,
    analyze_prompt, assess_source_quality, identify_missing_fields,
    auto_decide_depth, format_analysis_for_user,
)


# ============================================================
# URL 提取测试
# ============================================================

class TestUrlExtraction:
    def test_single_url(self):
        urls = extract_urls("看看这个 https://github.com/user/repo")
        assert len(urls) == 1
        assert urls[0] == "https://github.com/user/repo"

    def test_multiple_urls(self):
        text = "https://github.com/a/repo 和 https://arxiv.org/abs/2401.12345 这些"
        urls = extract_urls(text)
        assert len(urls) == 2

    def test_no_urls(self):
        urls = extract_urls("这是一段没有链接的文字")
        assert urls == []

    def test_url_with_punctuation(self):
        urls = extract_urls("链接：https://example.com/page，看看这个")
        assert urls[0] == "https://example.com/page"

    def test_bilibili_url(self):
        urls = extract_urls("https://www.bilibili.com/video/BV1xx411c7mD 这个视频")
        assert len(urls) == 1
        assert "bilibili.com" in urls[0]


# ============================================================
# Source Type 推断测试
# ============================================================

class TestSourceTypeInference:
    def test_github_repo(self):
        assert infer_source_type("https://github.com/user/repo") == "repo"

    def test_arxiv_pdf(self):
        assert infer_source_type("https://arxiv.org/abs/2401.12345") == "pdf"

    def test_youtube_video(self):
        assert infer_source_type("https://youtube.com/watch?v=abc") == "video"
        assert infer_source_type("https://youtu.be/abc") == "video"

    def test_bilibili_video(self):
        assert infer_source_type("https://bilibili.com/video/BV123") == "video"

    def test_pdf_direct(self):
        assert infer_source_type("https://example.com/paper.pdf") == "pdf"

    def test_article_default(self):
        assert infer_source_type("https://example.com/blog/post") == "article"

    def test_v2ex(self):
        assert infer_source_type("https://v2ex.com/t/12345") == "article"

    def test_zhihu(self):
        assert infer_source_type("https://zhihu.com/question/123") == "article"

    def test_npm(self):
        assert infer_source_type("https://npmjs.com/package/foo") == "tool"


# ============================================================
# Title 提取测试
# ============================================================

class TestTitleExtraction:
    def test_extract_from_prompt(self):
        prompt = "帮我分析 https://github.com/user/repo 这个 MCP 工具"
        urls = ["https://github.com/user/repo"]
        title = extract_title_from_prompt(prompt, urls)
        assert "MCP 工具" in title

    def test_empty_prompt(self):
        prompt = "https://example.com"
        urls = ["https://example.com"]
        title = extract_title_from_prompt(prompt, urls)
        assert title == ""

    def test_multi_url_extract(self):
        prompt = "分析这些：https://a.com https://b.com"
        urls = ["https://a.com", "https://b.com"]
        title = extract_title_from_prompt(prompt, urls)
        assert "分析这些" in title  # trailing colon may be stripped


# ============================================================
# Prompt 解析测试
# ============================================================

class TestAnalyzePrompt:
    def test_single_url_with_text(self):
        urls, intent, desc = analyze_prompt("帮我分析 https://github.com/user/repo")
        assert len(urls) == 1
        assert "帮我分析" in intent

    def test_ctw_ana_prefix(self):
        urls, intent, _ = analyze_prompt("/ctw_ana https://example.com 这个项目")
        assert len(urls) == 1
        assert "/ctw_ana" not in intent
        assert "这个项目" in intent

    def test_no_url(self):
        urls, intent, _ = analyze_prompt("帮我分析一些东西")
        assert urls == []
        assert "帮我分析一些东西" in intent


# ============================================================
# 质量评估测试
# ============================================================

class TestQualityAssessment:
    def test_full_quality(self):
        source = AnalyzedSource(
            url="https://example.com",
            title="A Great Tool",
            description="Amazing tool for stuff",
            content="## Overview\nThis is great.",
            source_type="article",
        )
        q = assess_source_quality(source)
        assert q >= 0.9

    def test_url_only(self):
        source = AnalyzedSource(url="https://example.com")
        q = assess_source_quality(source)
        assert q == 0.3  # only URL

    def test_url_and_title(self):
        source = AnalyzedSource(
            url="https://example.com",
            title="Some Tool",
        )
        q = assess_source_quality(source)
        assert q == 0.6  # URL + title

    def test_missing_fields(self):
        source = AnalyzedSource(url="https://example.com")
        missing = identify_missing_fields(source)
        assert "title" in missing
        assert "content" in missing


# ============================================================
# 智能深度决策测试
# ============================================================

class TestAutoDepthDecision:
    def test_tech_news_always_L0(self):
        cr = ClassifyResult(
            content_type=ContentType.TECH_NEWS,
            content_type_name="技术新闻",
            confidence=0.95,
            suggested_level=InfoLevel.L0,
        )
        level, reason = auto_decide_depth(cr, 0.9)
        assert level == InfoLevel.L0

    def test_security_always_L1(self):
        cr = ClassifyResult(
            content_type=ContentType.SECURITY_RESEARCH,
            content_type_name="安全研究",
            confidence=0.95,
            suggested_level=InfoLevel.L4,
        )
        level, reason = auto_decide_depth(cr, 0.9)
        assert level == InfoLevel.L1

    def test_low_quality_limit_L0(self):
        cr = ClassifyResult(
            content_type=ContentType.PAPER_REVIEW,
            content_type_name="论文解读",
            confidence=0.9,
            suggested_level=InfoLevel.L4,
        )
        level, reason = auto_decide_depth(cr, 0.2)
        assert level == InfoLevel.L0

    def test_low_confidence_downgrade(self):
        cr = ClassifyResult(
            content_type=ContentType.AI_AGENT,
            content_type_name="AI Agent",
            confidence=0.7,
            suggested_level=InfoLevel.L2,
        )
        level, _ = auto_decide_depth(cr, 0.8)
        assert level == InfoLevel.L1  # L2 - 1 = L1

    def test_high_confidence_full_depth(self):
        cr = ClassifyResult(
            content_type=ContentType.PAPER_REVIEW,
            content_type_name="论文解读",
            confidence=0.95,
            suggested_level=InfoLevel.L4,
        )
        level, _ = auto_decide_depth(cr, 0.9)
        assert level == InfoLevel.L4


# ============================================================
# CTWAnalyzer 主控测试
# ============================================================

class TestCTWAnalyzer:
    @pytest.fixture
    def analyzer(self):
        return CTWAnalyzer()

    def test_analyze_no_url(self, analyzer):
        result = analyzer.analyze("这是一段没有链接的文字")
        assert result.action_required is True
        assert "未检测到" in result.summary or "URL" in result.summary

    def test_analyze_single_github_url(self, analyzer):
        # Use a prompt with clear tool-extension keywords for the decision tree
        prompt = "帮我分析 https://github.com/modelcontextprotocol/servers 这个 MCP plugin 扩展"
        result = analyzer.analyze(prompt)
        assert len(result.sources) == 1
        assert result.sources[0].classify is not None
        ct = result.sources[0].classify.content_type
        assert ct == ContentType.TOOL_EXTENSION

    def test_analyze_paper_url(self, analyzer):
        prompt = "分析论文 https://arxiv.org/abs/2401.12345"
        result = analyzer.analyze(prompt)
        assert len(result.sources) == 1
        ct = result.sources[0].classify.content_type
        assert ct == ContentType.PAPER_REVIEW

    def test_analyze_multiple_urls(self, analyzer):
        prompt = "分析这些：https://github.com/user/tool 和 https://arxiv.org/abs/2401.12345"
        result = analyzer.analyze(prompt)
        assert len(result.sources) == 2

    def test_analyze_with_ask_first(self, analyzer):
        prompt = "https://some-random-url-12345.xyz/page"
        result = analyzer.analyze(prompt, auto_run=False)
        # URL only, low quality → should ask for more info
        # But auto_run=False doesn't skip classify, just returns with followups
        assert len(result.sources) == 1

    def test_analyze_returns_progress(self, analyzer):
        prompt = "帮我分析 https://github.com/user/repo 这个 MCP 项目"
        result = analyzer.analyze(prompt)
        assert result.progress is not None
        assert result.progress.total_sources == 1
        assert result.progress.stage == "done"

    def test_analyze_returns_summary(self, analyzer):
        prompt = "https://github.com/user/repo MCP FileSystem"
        result = analyzer.analyze(prompt)
        assert result.summary
        assert "CTW" in result.summary

    def test_analyze_returns_recommendations(self, analyzer):
        prompt = "https://github.com/user/repo MCP tool"
        result = analyzer.analyze(prompt)
        assert len(result.recommendations) > 0

    def test_status_report(self, analyzer):
        prompt = "https://github.com/user/repo"
        result = analyzer.analyze(prompt)
        status = analyzer.get_status(result)
        assert status["stage"] == "done"
        assert status["total"] == 1
        assert status["processed"] == 1

    def test_continue_analysis(self, analyzer):
        # First: analyze with low info
        result = analyzer.analyze("https://github.com/user/repo")
        assert len(result.sources) == 1

        # Supplement with more info
        supplements = {
            "https://github.com/user/repo": {
                "title": "MCP FileSystem Server",
                "content": "## Install\nnpm install @modelcontextprotocol/server-filesystem\n## Config\n..."
            }
        }
        result2 = analyzer.continue_analysis(result, supplements)
        assert result2.sources[0].title == "MCP FileSystem Server"
        assert result2.sources[0].classify is not None

    def test_format_analysis_for_user(self, analyzer):
        prompt = "https://github.com/user/repo MCP tool"
        result = analyzer.analyze(prompt)
        text = format_analysis_for_user(result)
        assert "CTW" in text
        assert isinstance(text, str)
        assert len(text) > 50

    def test_ctw_ana_convenience(self):
        result = ctw_ana("https://github.com/user/repo MCP tool")
        assert isinstance(result, AnalysisResult)
        assert len(result.sources) == 1


# ============================================================
# 边界情况测试
# ============================================================

class TestEdgeCases:
    @pytest.fixture
    def analyzer(self):
        return CTWAnalyzer()

    def test_empty_prompt(self, analyzer):
        result = analyzer.analyze("")
        assert result.action_required is True

    def test_very_long_url(self, analyzer):
        long_url = "https://example.com/" + "a" * 200
        result = analyzer.analyze(long_url)
        assert len(result.sources) == 1

    def test_url_with_special_chars(self, analyzer):
        prompt = "https://github.com/user/repo?tab=readme-ov-file#installation"
        result = analyzer.analyze(prompt)
        assert len(result.sources) == 1
        assert "readme" in result.sources[0].url

    def test_mixed_content_multiple_urls(self, analyzer):
        prompt = """帮我分析以下几个资料：
        1. n8n MCP 社区节点 https://github.com/n8n-io/n8n-nodes-mcp 这是一个 MCP 插件
        2. 关于大模型推理的论文 https://arxiv.org/abs/2401.12345
        """
        result = analyzer.analyze(prompt)
        assert len(result.sources) == 2

    def test_chinese_prompt_classification(self, analyzer):
        prompt = "分析这个安全漏洞 https://github.com/advisories/GHSA-xxxx 影响很大"
        result = analyzer.analyze(prompt)
        assert len(result.sources) == 1
        # Should classify as security research
        assert result.sources[0].classify is not None
        ct = result.sources[0].classify.content_type
        assert ct == ContentType.SECURITY_RESEARCH
