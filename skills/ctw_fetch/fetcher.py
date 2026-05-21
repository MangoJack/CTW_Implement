# -*- coding: utf-8 -*-
"""CTW Fetch — web resource fetching with type-specific extractors.

Fetches content from URLs, auto-detects source type, and returns a populated
SourceInput ready for the classification pipeline.

Source types and their fetch strategies:
  article  — generic web page: HTML → title, meta, OG tags, body text
  repo     — GitHub: API → name, description, README
  pdf      — arXiv: API → title, authors, abstract
  video    — YouTube (oEmbed) / Bilibili (page meta)
  tool     — npm/PyPI/crates.io: registry API
  model    — HuggingFace: model card API
"""

import json
import re
import sys
import os
import time
import hashlib
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional, Callable
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urljoin

# Ensure lib/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "lib"))

from ctw_types import SourceInput

# ── Constants ────────────────────────────────────────────────────

TIMEOUT = 15
USER_AGENT = (
    "CTW-Implement/1.0 (Information Processing Pipeline; "
    "+https://github.com/ctw-implement)"
)
MAX_CONTENT_LENGTH = 5000  # chars to keep from body text

# ── Domain → source_type mapping ─────────────────────────────────

DOMAIN_TYPE_MAP: dict[str, str] = {
    "github.com": "repo",
    "arxiv.org": "pdf",
    "youtube.com": "video",
    "youtu.be": "video",
    "bilibili.com": "video",
    "v2ex.com": "article",
    "zhihu.com": "article",
    "sspai.com": "article",
    "medium.com": "article",
    "reddit.com": "article",
    "twitter.com": "article",
    "x.com": "article",
    "npmjs.com": "tool",
    "pypi.org": "tool",
    "crates.io": "tool",
    "huggingface.co": "model",
}

# ── Utility ──────────────────────────────────────────────────────

def infer_source_type(url: str) -> str:
    """Infer CTW source_type from URL domain and path."""
    parsed = urlparse(url)
    domain = parsed.hostname or ""
    for key, stype in DOMAIN_TYPE_MAP.items():
        if key in domain:
            return stype
    if parsed.path.lower().endswith(".pdf"):
        return "pdf"
    return "article"


def _http_get(url: str, headers: dict = None, timeout: int = TIMEOUT) -> str:
    """HTTP GET, return decoded response body. Raises on failure."""
    req = Request(url)
    req.add_header("User-Agent", USER_AGENT)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    with urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
        return data.decode(charset, errors="replace")


def _http_get_json(url: str, timeout: int = TIMEOUT) -> dict:
    """HTTP GET and parse JSON response body."""
    body = _http_get(url, {"Accept": "application/json"}, timeout)
    return json.loads(body)


# ── HTML extraction ──────────────────────────────────────────────

class _MetaExtractor(HTMLParser):
    """Extract <title>, <meta name/og>, and body text from HTML."""

    def __init__(self):
        super().__init__()
        self.title = ""
        self.description = ""
        self.og_title = ""
        self.og_description = ""
        self.body_text: list[str] = []
        self._in_title = False
        self._in_body = False
        self._in_script = False
        self._in_style = False
        self._skip_tags = {"script", "style", "noscript", "iframe", "svg"}
        self._char_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str]]):
        attrs_dict = dict(attrs)
        tag_l = tag.lower()
        if tag_l == "title":
            self._in_title = True
        elif tag_l == "body":
            self._in_body = True
        elif tag_l in self._skip_tags:
            self._in_script = True if tag_l == "script" else self._in_script
            self._in_style = True if tag_l == "style" else self._in_style
        elif tag_l == "meta":
            name = attrs_dict.get("name", "").lower()
            prop = attrs_dict.get("property", "").lower()
            content = attrs_dict.get("content", "")
            if name == "description":
                self.description = content
            elif prop == "og:title":
                self.og_title = content
            elif prop == "og:description":
                self.og_description = content

    def handle_endtag(self, tag: str):
        tag_l = tag.lower()
        if tag_l == "title":
            self._in_title = False
        elif tag_l in self._skip_tags:
            if tag_l == "script":
                self._in_script = False
            elif tag_l == "style":
                self._in_style = False

    def handle_data(self, data: str):
        if self._in_title and not self.title:
            self.title = data.strip()
        elif self._in_body and not self._in_script and not self._in_style:
            if self._char_count < MAX_CONTENT_LENGTH:
                text = data.strip()
                if text:
                    self.body_text.append(text)
                    self._char_count += len(text)


def _extract_html(html: str) -> tuple[str, str, str]:
    """Parse HTML; return (title, description, body_text)."""
    parser = _MetaExtractor()
    try:
        parser.feed(html)
    except Exception:
        pass
    title = parser.og_title or parser.title or ""
    desc = parser.og_description or parser.description or ""
    body = "\n".join(parser.body_text)
    return title, desc, body


# ── Type-specific fetchers ───────────────────────────────────────

def _fetch_web_page(url: str) -> SourceInput:
    """Fetch a generic web page — extract title, description, body text."""
    try:
        html = _http_get(url)
        title, desc, body = _extract_html(html)
        return SourceInput(
            url=url,
            title=title or "",
            description=desc or "",
            content=body[:MAX_CONTENT_LENGTH],
            source_type="article",
        )
    except Exception as e:
        return SourceInput(url=url, source_type="article",
                           description=f"Fetch failed: {e}")


def _fetch_github_repo(url: str) -> SourceInput:
    """Fetch GitHub repo using API: owner/repo from URL path."""
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    parts = path.split("/")
    if len(parts) >= 2:
        owner, repo = parts[0], parts[1].rstrip(".git")
    else:
        # Not a standard GitHub repo URL — fall back to web page fetch
        return _fetch_web_page(url)

    try:
        data = _http_get_json(f"https://api.github.com/repos/{owner}/{repo}")
        title = data.get("full_name", f"{owner}/{repo}")
        desc = data.get("description", "")
        topics = data.get("topics", [])
        lang = data.get("language", "")
        stars = data.get("stargazers_count", 0)
        license_info = data.get("license") or {}
        license_name = license_info.get("spdx_id", "")

        metadata_lines = [
            f"Repository: {title}",
            f"Description: {desc}",
            f"Language: {lang or 'unknown'}",
            f"Stars: {stars}",
            f"License: {license_name or 'unknown'}",
            f"Topics: {', '.join(topics[:10])}",
        ]

        # Try fetching README content
        try:
            readme_data = _http_get_json(
                f"https://api.github.com/repos/{owner}/{repo}/readme",
            )
            readme_url = readme_data.get("download_url", "")
            if readme_url:
                readme_text = _http_get(readme_url)
                # Truncate README to keep content manageable
                readme_text = readme_text[:MAX_CONTENT_LENGTH]
                metadata_lines.append(f"\n--- README ---\n{readme_text}")
        except Exception:
            pass

        return SourceInput(
            url=url,
            title=title,
            description=desc or "",
            content="\n".join(metadata_lines),
            source_type="repo",
        )
    except Exception as e:
        return SourceInput(url=url, source_type="repo",
                           description=f"GitHub fetch failed: {e}")


def _fetch_arxiv(url: str) -> SourceInput:
    """Fetch arXiv paper metadata via the arXiv API."""
    # Extract arXiv ID from URL
    arxiv_id = ""
    parsed = urlparse(url)
    path = parsed.path
    # Patterns: /abs/<id>, /pdf/<id>, /html/<id>
    m = re.search(r"/(?:abs|pdf|html)/(\d+\.\d+(?:v\d+)?)", path)
    if m:
        arxiv_id = m.group(1)

    if not arxiv_id:
        return _fetch_web_page(url)

    try:
        api_url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}&max_results=1"
        xml = _http_get(api_url)

        # Simple XML extraction (stdlib xml.etree can't handle namespaces well,
        # use regex for the key fields we need)
        title_m = re.search(r"<title>(.*?)</title>", xml, re.DOTALL)
        # The first <title> is the feed title; the second is the paper title
        titles = re.findall(r"<title>(.*?)</title>", xml, re.DOTALL)
        paper_title = titles[1].strip() if len(titles) > 1 else (title_m.group(1).strip() if title_m else "")

        abstract_m = re.search(r"<summary>(.*?)</summary>", xml, re.DOTALL)
        abstract = abstract_m.group(1).strip() if abstract_m else ""

        authors = re.findall(r"<author>.*?<name>(.*?)</name>.*?</author>", xml, re.DOTALL)
        published_m = re.search(r"<published>(\d{4}-\d{2}-\d{2})", xml)

        content_lines = [
            f"Title: {paper_title}",
            f"Authors: {', '.join(authors) if authors else 'unknown'}",
            f"Published: {published_m.group(1) if published_m else 'unknown'}",
            f"arXiv ID: {arxiv_id}",
            f"\n--- Abstract ---\n{abstract}",
        ]

        return SourceInput(
            url=url,
            title=paper_title,
            description=abstract[:500] if abstract else "",
            content="\n".join(content_lines),
            source_type="pdf",
        )
    except Exception as e:
        return SourceInput(url=url, source_type="pdf",
                           description=f"arXiv fetch failed: {e}")


def _fetch_youtube(url: str) -> SourceInput:
    """Fetch YouTube video metadata via oEmbed."""
    try:
        oembed_url = f"https://www.youtube.com/oembed?url={url}&format=json"
        data = _http_get_json(oembed_url)
        title = data.get("title", "")
        author = data.get("author_name", "")
        return SourceInput(
            url=url,
            title=title,
            description=f"Channel: {author}",
            content=f"Title: {title}\nChannel: {author}",
            source_type="video",
        )
    except Exception:
        # Fallback: fetch the page and extract title
        try:
            html = _http_get(url)
            title_m = re.search(r'<meta\s+name="title"\s+content="([^"]+)"', html)
            if not title_m:
                title_m = re.search(r"<title>(.*?)</title>", html, re.DOTALL)
            title = title_m.group(1).strip() if title_m else ""
            title = title.replace(" - YouTube", "").strip()
            return SourceInput(
                url=url,
                title=title,
                content=f"Title: {title}",
                source_type="video",
            )
        except Exception as e:
            return SourceInput(url=url, source_type="video",
                               description=f"YouTube fetch failed: {e}")


def _fetch_bilibili(url: str) -> SourceInput:
    """Fetch Bilibili video metadata from page meta tags."""
    try:
        html = _http_get(url)
        title_m = re.search(r'<meta\s+[^>]*name="title"\s+content="([^"]+)"', html, re.IGNORECASE)
        if not title_m:
            title_m = re.search(r"<title>(.*?)</title>", html, re.DOTALL)
        title = title_m.group(1).strip() if title_m else ""

        desc_m = re.search(r'<meta\s+[^>]*name="description"\s+content="([^"]+)"', html, re.IGNORECASE)
        description = desc_m.group(1).strip() if desc_m else ""

        # Clean up title (Bilibili appends site name)
        title = re.sub(r"_哔哩哔哩.*$", "", title).strip()

        return SourceInput(
            url=url,
            title=title,
            description=description[:500] if description else "",
            content=f"Title: {title}\nDescription: {description[:2000]}",
            source_type="video",
        )
    except Exception as e:
        return SourceInput(url=url, source_type="video",
                           description=f"Bilibili fetch failed: {e}")


def _fetch_package_registry(url: str) -> SourceInput:
    """Fetch package metadata from npm / PyPI / crates.io."""
    parsed = urlparse(url)
    domain = parsed.hostname or ""

    try:
        if "npmjs.com" in domain or "npm.im" in domain:
            return _fetch_npm(url, parsed)
        elif "pypi.org" in domain:
            return _fetch_pypi(url, parsed)
        elif "crates.io" in domain:
            return _fetch_crates(url, parsed)
        else:
            return _fetch_web_page(url)
    except Exception as e:
        return SourceInput(url=url, source_type="tool",
                           description=f"Package fetch failed: {e}")


def _fetch_npm(url: str, parsed=None) -> SourceInput:
    """Fetch npm package metadata from registry.npmjs.org."""
    if parsed is None:
        parsed = urlparse(url)
    path = parsed.path.strip("/")
    # /package/<name> or /package/<name>/v/<version>
    m = re.search(r"package/(@?[\w.-]+(?:/[\w.-]+)?)", path)
    if not m:
        return _fetch_web_page(url)
    pkg_name = m.group(1)
    data = _http_get_json(f"https://registry.npmjs.org/{pkg_name}/latest")
    title = data.get("name", pkg_name)
    desc = data.get("description", "")
    version = data.get("version", "")
    license_info = data.get("license", "")
    keywords = data.get("keywords", [])

    return SourceInput(
        url=url,
        title=title,
        description=desc or "",
        content=f"Package: {title}\nVersion: {version}\nLicense: {license_info}\n"
                f"Description: {desc}\nKeywords: {', '.join(keywords[:10])}",
        source_type="tool",
    )


def _fetch_pypi(url: str, parsed=None) -> SourceInput:
    """Fetch PyPI package metadata."""
    if parsed is None:
        parsed = urlparse(url)
    path = parsed.path.strip("/")
    m = re.search(r"(?:pypi/|project/)([\w.-]+)", path)
    if not m:
        return _fetch_web_page(url)
    pkg_name = m.group(1)
    data = _http_get_json(f"https://pypi.org/pypi/{pkg_name}/json")
    info = data.get("info", {})
    title = info.get("name", pkg_name)
    desc = info.get("summary", "")
    version = info.get("version", "")
    license_info = info.get("license", "")
    keywords = info.get("keywords", "")

    return SourceInput(
        url=url,
        title=title,
        description=desc or "",
        content=f"Package: {title}\nVersion: {version}\nLicense: {license_info}\n"
                f"Description: {desc}\nKeywords: {keywords}",
        source_type="tool",
    )


def _fetch_crates(url: str, parsed=None) -> SourceInput:
    """Fetch crates.io package metadata."""
    if parsed is None:
        parsed = urlparse(url)
    path = parsed.path.strip("/")
    m = re.search(r"crates/([\w.-]+)", path)
    if not m:
        return _fetch_web_page(url)
    pkg_name = m.group(1)
    data = _http_get_json(f"https://crates.io/api/v1/crates/{pkg_name}")
    crate = data.get("crate", {})
    title = crate.get("name", pkg_name)
    desc = crate.get("description", "")
    version = crate.get("max_stable_version", crate.get("max_version", ""))
    license_info = crate.get("license", "")

    return SourceInput(
        url=url,
        title=title,
        description=desc or "",
        content=f"Crate: {title}\nVersion: {version}\nLicense: {license_info}\n"
                f"Description: {desc}",
        source_type="tool",
    )


def _fetch_huggingface(url: str) -> SourceInput:
    """Fetch HuggingFace model card metadata."""
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    # Pattern: /owner/model_name or /owner/model_name/tree/main
    parts = [p for p in path.split("/") if p and p != "tree" and p != "blob"]
    if len(parts) >= 2:
        model_id = f"{parts[0]}/{parts[1]}"
    else:
        return _fetch_web_page(url)

    try:
        data = _http_get_json(f"https://huggingface.co/api/models/{model_id}")
        title = data.get("modelId", model_id)
        desc = data.get("pipeline_tag", "")
        tags = data.get("tags", [])
        downloads = data.get("downloads", 0)
        likes = data.get("likes", 0)
        task = data.get("pipeline_tag", "unknown")

        # Try to get model card
        card_text = ""
        try:
            card_url = f"https://huggingface.co/{model_id}/raw/main/README.md"
            card_text = _http_get(card_url)[:MAX_CONTENT_LENGTH]
        except Exception:
            pass

        content = (
            f"Model: {title}\nTask: {task}\nDownloads: {downloads}\n"
            f"Likes: {likes}\nTags: {', '.join(tags[:10])}\n"
            f"Description: {desc}"
        )
        if card_text:
            content += f"\n\n--- Model Card ---\n{card_text}"

        return SourceInput(
            url=url,
            title=title,
            description=desc,
            content=content,
            source_type="model",
        )
    except Exception as e:
        return SourceInput(url=url, source_type="model",
                           description=f"HuggingFace fetch failed: {e}")


# ── Dispatcher ───────────────────────────────────────────────────

_FETCHER_MAP: dict[str, Callable[[str], SourceInput]] = {
    "article": _fetch_web_page,
    "repo": _fetch_github_repo,
    "pdf": _fetch_arxiv,
    "video": lambda url: (
        _fetch_youtube(url) if ("youtube.com" in url or "youtu.be" in url)
        else _fetch_bilibili(url)
    ),
    "tool": _fetch_package_registry,
    "model": _fetch_huggingface,
}


class ResourceFetcher:
    """Fetch web resources and return populated SourceInput objects.

    Usage:
        fetcher = ResourceFetcher()
        source = fetcher.fetch("https://github.com/user/repo")
        # source.title, source.description, source.content are now populated
    """

    def fetch(self, url: str, source_type: str = None) -> SourceInput:
        """Fetch content from a URL and return a populated SourceInput.

        Args:
            url: The URL to fetch.
            source_type: Override auto-detection (article/repo/pdf/video/tool/model).

        Returns:
            SourceInput with title, description, content, and source_type populated.
            Fields may be empty on fetch failures (no exceptions raised).
        """
        if not url:
            return SourceInput(url="", source_type="")

        if source_type is None:
            source_type = infer_source_type(url)

        fetcher = _FETCHER_MAP.get(source_type, _fetch_web_page)
        result = fetcher(url)

        # Generate raw_file_path slug based on URL
        if result.url:
            slug = hashlib.md5(result.url.encode()).hexdigest()[:12]
            ext_map = {
                "repo": ".json",
                "pdf": ".txt",
                "video": ".json",
                "tool": ".json",
                "model": ".json",
                "article": ".html",
            }
            ext = ext_map.get(result.source_type, ".txt")
            result.raw_file_path = f"raw/{source_type}s/{slug}{ext}"

        return result

    def fetch_batch(self, urls: list[str]) -> list[SourceInput]:
        """Fetch multiple URLs (sequential, not parallel)."""
        return [self.fetch(url) for url in urls]
