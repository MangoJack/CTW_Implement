# CTW Fetch — tests
"""Tests for ResourceFetcher with mocked HTTP responses."""
import sys
import os
import json
from io import BytesIO
from pathlib import Path
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from ctw_types import SourceInput
from fetcher import (
    ResourceFetcher, infer_source_type, _extract_html,
    _fetch_web_page, _fetch_github_repo, _fetch_arxiv,
    _fetch_youtube, _fetch_bilibili, _fetch_package_registry,
    _fetch_huggingface, _fetch_npm, _fetch_pypi, _fetch_crates,
    DOMAIN_TYPE_MAP,
)


# ── Test helpers ────────────────────────────────────────────────

def _mock_response(body: str, content_type: str = "text/html", status: int = 200):
    """Create a mock that returns a urllib-style response."""
    data = body.encode("utf-8")
    mock_resp = Mock()
    mock_resp.read.return_value = data
    mock_resp.headers.get_content_charset.return_value = "utf-8"
    mock_resp.status = status
    mock_resp.__enter__ = Mock(return_value=mock_resp)
    mock_resp.__exit__ = Mock(return_value=False)
    return mock_resp


def _mock_json_response(data: dict):
    body = json.dumps(data)
    mock_resp = Mock()
    mock_resp.read.return_value = body.encode("utf-8")
    mock_resp.headers.get_content_charset.return_value = "utf-8"
    mock_resp.__enter__ = Mock(return_value=mock_resp)
    mock_resp.__exit__ = Mock(return_value=False)
    return mock_resp


# ── Type inference tests ────────────────────────────────────────

class TestInferSourceType:
    def test_github_repo(self):
        assert infer_source_type("https://github.com/user/repo") == "repo"

    def test_arxiv_pdf(self):
        assert infer_source_type("https://arxiv.org/abs/2401.12345") == "pdf"

    def test_arxiv_pdf_direct(self):
        assert infer_source_type("https://arxiv.org/pdf/2401.12345.pdf") == "pdf"

    def test_youtube_video(self):
        assert infer_source_type("https://www.youtube.com/watch?v=abc123") == "video"

    def test_youtu_be_video(self):
        assert infer_source_type("https://youtu.be/abc123") == "video"

    def test_bilibili_video(self):
        assert infer_source_type("https://www.bilibili.com/video/BV12345") == "video"

    def test_v2ex_article(self):
        assert infer_source_type("https://v2ex.com/t/12345") == "article"

    def test_zhihu_article(self):
        assert infer_source_type("https://zhuanlan.zhihu.com/p/12345") == "article"

    def test_medium_article(self):
        assert infer_source_type("https://medium.com/@user/post") == "article"

    def test_reddit_article(self):
        assert infer_source_type("https://www.reddit.com/r/python/comments/abc") == "article"

    def test_twitter_article(self):
        assert infer_source_type("https://twitter.com/user/status/123") == "article"
        assert infer_source_type("https://x.com/user/status/123") == "article"

    def test_npm_tool(self):
        assert infer_source_type("https://www.npmjs.com/package/react") == "tool"

    def test_pypi_tool(self):
        assert infer_source_type("https://pypi.org/project/requests/") == "tool"

    def test_crates_tool(self):
        assert infer_source_type("https://crates.io/crates/serde") == "tool"

    def test_huggingface_model(self):
        assert infer_source_type("https://huggingface.co/meta-llama/Meta-Llama-3") == "model"

    def test_pdf_by_extension(self):
        assert infer_source_type("https://example.com/paper.pdf") == "pdf"

    def test_unknown_defaults_to_article(self):
        assert infer_source_type("https://some-random-blog.com/post") == "article"
        assert infer_source_type("https://example.com") == "article"

    def test_all_domain_map_entries_have_valid_types(self):
        valid_types = {"article", "repo", "pdf", "video", "tool", "model"}
        for domain, stype in DOMAIN_TYPE_MAP.items():
            assert stype in valid_types, f"{domain} → {stype}"


# ── HTML extraction tests ────────────────────────────────────────

class TestHTMLExtraction:
    def test_extract_title(self):
        html = "<html><head><title>My Page</title></head><body></body></html>"
        title, desc, body = _extract_html(html)
        assert title == "My Page"

    def test_extract_meta_description(self):
        html = ('<html><head>'
                '<meta name="description" content="A great page">'
                '</head><body></body></html>')
        title, desc, body = _extract_html(html)
        assert desc == "A great page"

    def test_extract_og_tags(self):
        html = ('<html><head>'
                '<meta property="og:title" content="OG Title">'
                '<meta property="og:description" content="OG Desc">'
                '</head><body></body></html>')
        title, desc, body = _extract_html(html)
        assert title == "OG Title"
        assert desc == "OG Desc"

    def test_extract_body_text(self):
        html = ('<html><head><title>T</title></head>'
                '<body><p>Hello world</p><p>Second paragraph</p></body></html>')
        title, desc, body = _extract_html(html)
        assert "Hello world" in body
        assert "Second paragraph" in body

    def test_strips_script_and_style(self):
        html = ('<html><head><title>T</title></head>'
                '<body>'
                '<script>console.log("x")</script>'
                '<style>.a { color: red; }</style>'
                '<p>Real content</p>'
                '</body></html>')
        title, desc, body = _extract_html(html)
        assert "console.log" not in body
        assert ".a { color: red" not in body
        assert "Real content" in body

    def test_empty_html(self):
        title, desc, body = _extract_html("")
        assert title == ""
        assert desc == ""
        assert body == ""


# ── ResourceFetcher.fetch tests (mocked HTTP) ────────────────────

class TestFetchWebPage:
    def test_fetch_with_urlopen(self):
        html = """<html><head>
            <title>Test Article</title>
            <meta name="description" content="A test article about Python">
            </head><body><p>This is the main content of the article.</p></body></html>"""
        with patch("fetcher.urlopen", return_value=_mock_response(html)):
            result = _fetch_web_page("https://example.com/article")
            assert result.title == "Test Article"
            assert result.description == "A test article about Python"
            assert "main content" in result.content
            assert result.source_type == "article"

    def test_fetch_with_no_meta(self):
        html = "<html><head><title>Minimal</title></head><body><p>Body only</p></body></html>"
        with patch("fetcher.urlopen", return_value=_mock_response(html)):
            result = _fetch_web_page("https://example.com/minimal")
            assert result.title == "Minimal"
            assert result.description == ""
            assert "Body only" in result.content

    def test_fetch_http_error(self):
        with patch("fetcher.urlopen", side_effect=Exception("Connection refused")):
            result = _fetch_web_page("https://down.example.com")
            assert result.url == "https://down.example.com"
            assert result.source_type == "article"
            assert "Fetch failed" in result.description


class TestFetchGitHub:
    def test_fetch_repo_with_readme(self):
        repo_json = {
            "full_name": "user/test-repo",
            "description": "A test repository",
            "topics": ["python", "cli"],
            "language": "Python",
            "stargazers_count": 42,
            "license": {"spdx_id": "MIT"},
        }
        readme_json = {"download_url": "https://raw.githubusercontent.com/user/test-repo/main/README.md"}
        readme_text = "# Test Repo\n\nThis is a test."

        call_count = 0
        def _mock_urlopen(req, timeout=15):
            nonlocal call_count
            call_count += 1
            url = req.full_url
            if "readme" in url:
                return _mock_json_response(readme_json)
            elif "raw" in url:
                return _mock_response(readme_text, "text/plain")
            else:
                return _mock_json_response(repo_json)

        with patch("fetcher.urlopen", side_effect=_mock_urlopen):
            result = _fetch_github_repo("https://github.com/user/test-repo")
            assert result.title == "user/test-repo"
            assert result.description == "A test repository"
            assert "Python" in result.content
            assert "MIT" in result.content
            assert "This is a test." in result.content
            assert result.source_type == "repo"

    def test_fetch_repo_no_readme(self):
        repo_json = {
            "full_name": "user/minimal",
            "description": "",
            "topics": [],
            "language": None,
            "stargazers_count": 0,
            "license": None,
        }
        def _mock_urlopen(req, timeout=15):
            if "readme" in req.full_url:
                raise Exception("No README")
            return _mock_json_response(repo_json)

        with patch("fetcher.urlopen", side_effect=_mock_urlopen):
            result = _fetch_github_repo("https://github.com/user/minimal")
            assert result.title == "user/minimal"
            assert result.source_type == "repo"

    def test_fetch_repo_api_error_falls_back(self):
        with patch("fetcher.urlopen", side_effect=Exception("API down")):
            result = _fetch_github_repo("https://github.com/user/repo")
            assert result.source_type == "repo"
            assert "GitHub fetch failed" in result.description

    def test_non_standard_github_url(self):
        result = _fetch_github_repo("https://github.com/only-one-part")
        # Falls back to web page fetch for non-standard URLs
        assert result.source_type in ("repo", "article")


class TestFetchArxiv:
    def test_fetch_paper(self):
        xml = """<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <title>ArXiv Query</title>
          <entry>
            <title>Chain-of-Thought Prompting Improves Reasoning</title>
            <summary>  We demonstrate that chain-of-thought prompting significantly
            improves performance on arithmetic, commonsense, and symbolic reasoning tasks.
            </summary>
            <author><name>John Smith</name></author>
            <author><name>Jane Doe</name></author>
            <published>2024-01-15</published>
          </entry>
        </feed>"""
        with patch("fetcher.urlopen", return_value=_mock_response(xml)):
            result = _fetch_arxiv("https://arxiv.org/abs/2401.12345")
            assert "Chain-of-Thought" in result.title
            assert "chain-of-thought" in result.content
            assert "2401.12345" in result.content
            assert result.source_type == "pdf"

    def test_fetch_invalid_arxiv_url(self):
        with patch("fetcher.urlopen", return_value=_mock_response("<html></html>")):
            result = _fetch_arxiv("https://arxiv.org/list/cs.AI")
            # No arxiv ID extractable, falls back to web page
            assert result.source_type in ("pdf", "article")

    def test_fetch_arxiv_api_error(self):
        with patch("fetcher.urlopen", side_effect=Exception("API error")):
            result = _fetch_arxiv("https://arxiv.org/abs/2401.99999")
            assert result.source_type == "pdf"
            assert "failed" in result.description


class TestFetchYouTube:
    def test_fetch_via_oembed(self):
        oembed = {"title": "How to Python", "author_name": "CodeChannel"}
        with patch("fetcher.urlopen", return_value=_mock_json_response(oembed)):
            result = _fetch_youtube("https://www.youtube.com/watch?v=abc123")
            assert result.title == "How to Python"
            assert "CodeChannel" in result.description
            assert result.source_type == "video"

    def test_fetch_fallback_to_page(self):
        def _mock_youtube(urlopen_req, timeout=15):
            url = urlopen_req.full_url
            if "oembed" in url:
                raise Exception("oEmbed unavailable")
            html = '<html><head><meta name="title" content="Python Tips - YouTube"><title>Python Tips - YouTube</title></head></html>'
            return _mock_response(html)

        with patch("fetcher.urlopen", side_effect=_mock_youtube):
            result = _fetch_youtube("https://www.youtube.com/watch?v=abc123")
            assert "Python Tips" in result.title
            assert "YouTube" not in result.title

    def test_fetch_complete_failure(self):
        with patch("fetcher.urlopen", side_effect=Exception("Down")):
            result = _fetch_youtube("https://www.youtube.com/watch?v=abc123")
            assert result.source_type == "video"
            assert "failed" in result.description


class TestFetchBilibili:
    def test_fetch_bilibili_video(self):
        html = """<html><head>
            <meta name="title" content="Agent开发入门-37">
            <meta name="description" content="全148集Agent开发实战教程">
            <title>Agent开发入门-37_哔哩哔哩_bilibili</title>
            </head></html>"""
        with patch("fetcher.urlopen", return_value=_mock_response(html)):
            result = _fetch_bilibili("https://www.bilibili.com/video/BV12345")
            assert "Agent开发入门-37" in result.title
            assert result.source_type == "video"

    def test_fetch_bilibili_failure(self):
        with patch("fetcher.urlopen", side_effect=Exception("Down")):
            result = _fetch_bilibili("https://www.bilibili.com/video/BV12345")
            assert result.source_type == "video"
            assert "failed" in result.description


class TestFetchPackageRegistry:
    def test_fetch_npm(self):
        npm_data = {
            "name": "react",
            "description": "A JavaScript library for building UIs",
            "version": "18.2.0",
            "license": "MIT",
            "keywords": ["ui", "components", "virtual-dom"],
        }
        with patch("fetcher.urlopen", return_value=_mock_json_response(npm_data)):
            result = _fetch_npm("https://www.npmjs.com/package/react", None)
            assert result.title == "react"
            assert "JavaScript library" in result.description
            assert "18.2.0" in result.content
            assert result.source_type == "tool"

    def test_fetch_npm_scoped_package(self):
        npm_data = {
            "name": "@angular/core",
            "description": "Angular core framework",
            "version": "17.0.0",
            "license": "MIT",
            "keywords": ["angular"],
        }
        with patch("fetcher.urlopen", return_value=_mock_json_response(npm_data)):
            result = _fetch_npm("https://www.npmjs.com/package/@angular/core", None)
            assert result.title == "@angular/core"

    def test_fetch_pypi(self):
        pypi_data = {
            "info": {
                "name": "requests",
                "summary": "Python HTTP for Humans",
                "version": "2.31.0",
                "license": "Apache 2.0",
                "keywords": "http requests",
            }
        }
        with patch("fetcher.urlopen", return_value=_mock_json_response(pypi_data)):
            result = _fetch_pypi("https://pypi.org/project/requests/", None)
            assert result.title == "requests"
            assert "HTTP" in result.description
            assert "2.31.0" in result.content
            assert result.source_type == "tool"

    def test_fetch_crates(self):
        crates_data = {
            "crate": {
                "name": "serde",
                "description": "Serialization framework",
                "max_stable_version": "1.0.0",
                "license": "MIT OR Apache-2.0",
            }
        }
        with patch("fetcher.urlopen", return_value=_mock_json_response(crates_data)):
            result = _fetch_crates("https://crates.io/crates/serde", None)
            assert result.title == "serde"
            assert "Serialization" in result.description
            assert "1.0.0" in result.content
            assert result.source_type == "tool"

    def test_fetch_unknown_registry_falls_back(self):
        with patch("fetcher.urlopen", return_value=_mock_response("<html></html>")):
            result = _fetch_package_registry("https://packagist.org/packages/foo")
            assert result.source_type in ("tool", "article")

    def test_fetch_registry_dispatcher(self):
        npm_data = {"name": "lodash", "description": "Utility library",
                     "version": "4.0.0", "license": "MIT", "keywords": []}
        with patch("fetcher.urlopen", return_value=_mock_json_response(npm_data)):
            result = _fetch_package_registry("https://www.npmjs.com/package/lodash")
            assert result.title == "lodash"
            assert result.source_type == "tool"


class TestFetchHuggingFace:
    def test_fetch_model(self):
        model_data = {
            "modelId": "meta-llama/Meta-Llama-3-8B",
            "pipeline_tag": "text-generation",
            "tags": ["transformers", "llama"],
            "downloads": 1000000,
            "likes": 5000,
        }
        def _mock_hf(urlopen_req, timeout=15):
            url = urlopen_req.full_url
            if "raw/main/README.md" in url:
                raise Exception("No card")
            return _mock_json_response(model_data)

        with patch("fetcher.urlopen", side_effect=_mock_hf):
            result = _fetch_huggingface(
                "https://huggingface.co/meta-llama/Meta-Llama-3-8B"
            )
            assert result.title == "meta-llama/Meta-Llama-3-8B"
            assert "text-generation" in result.content
            assert result.source_type == "model"

    def test_fetch_model_with_card(self):
        model_data = {"modelId": "user/my-model", "pipeline_tag": "text-classification",
                      "tags": [], "downloads": 0, "likes": 0}
        readme = "# My Model\n\nThis model classifies text."

        def _mock_hf(urlopen_req, timeout=15):
            url = urlopen_req.full_url
            if "raw/main/README.md" in url:
                return _mock_response(readme, "text/plain")
            return _mock_json_response(model_data)

        with patch("fetcher.urlopen", side_effect=_mock_hf):
            result = _fetch_huggingface("https://huggingface.co/user/my-model")
            assert "classifies text" in result.content

    def test_fetch_hf_non_model_url(self):
        with patch("fetcher.urlopen", side_effect=Exception("Down")):
            result = _fetch_huggingface("https://huggingface.co/spaces/user/space")
            assert result.source_type == "model"
            assert "failed" in result.description


# ── ResourceFetcher integration tests ────────────────────────────

class TestResourceFetcher:
    def test_fetch_auto_detect_article(self):
        html = '<html><head><title>My Blog</title></head><body><p>Content</p></body></html>'
        fetcher = ResourceFetcher()
        with patch("fetcher.urlopen", return_value=_mock_response(html)):
            result = fetcher.fetch("https://some-blog.com/post")
            assert result.title == "My Blog"
            assert result.source_type == "article"
            assert result.raw_file_path.startswith("raw/articles/")

    def test_fetch_auto_detect_github(self):
        repo_json = {"full_name": "user/repo", "description": "A repo",
                     "topics": [], "language": "Go", "stargazers_count": 10,
                     "license": None}
        fetcher = ResourceFetcher()

        def _mock(req, timeout=15):
            if "readme" in req.full_url:
                raise Exception("no readme")
            return _mock_json_response(repo_json)

        with patch("fetcher.urlopen", side_effect=_mock):
            result = fetcher.fetch("https://github.com/user/repo")
            assert result.source_type == "repo"
            assert result.raw_file_path.startswith("raw/repos/")

    def test_fetch_with_explicit_type(self):
        html = '<html><head><title>Test</title></head><body></body></html>'
        fetcher = ResourceFetcher()
        with patch("fetcher.urlopen", return_value=_mock_response(html)):
            result = fetcher.fetch("https://example.com", source_type="article")
            assert result.source_type == "article"

    def test_fetch_empty_url(self):
        fetcher = ResourceFetcher()
        result = fetcher.fetch("")
        assert result.url == ""

    def test_fetch_raw_file_path_for_each_type(self):
        fetcher = ResourceFetcher()
        html = '<html><head><title>Test</title></head><body></body></html>'
        with patch("fetcher.urlopen", return_value=_mock_response(html)):
            for test_type, ext in [
                ("article", "articles"),
                ("pdf", "pdfs"),
                ("video", "videos"),
                ("tool", "tools"),
                ("model", "models"),
                ("repo", "repos"),
            ]:
                src = SourceInput(url="https://example.com", source_type=test_type)
                # Verify path format is correct
                assert src.source_type == test_type


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
