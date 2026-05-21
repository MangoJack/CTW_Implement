"""CTW Ingest Skill — LLM Wiki 摄入管道

源 → 摘要 → 概念 → 实体 → 对比 → ZK候选

所有产出文件写入人类指定的仓库目录（通过 CTWConfig.repository_path 配置）。
仓库目录结构:
  {repo}/
    wiki/
      sources/      源摘要页
      entities/     实体页
      concepts/     概念页
      comparisons/  对比页
    zk/             ZK 永久笔记
"""
import re
import sys
import os
import hashlib
import time
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))
from ctw_types import (
    ContentType, InfoLevel, SourceInput, ClassifyResult,
    LevelResult, IngestResult, ZkCandidate,
)
from ctw_config import CTWConfig
from ctw_templates import TemplateEngine

try:
    from ctw_llm import get_client as _get_llm_client
except ImportError:
    _get_llm_client = None


# ============================================================
# Templates (inline, to avoid filesystem dependency in tests)
# ============================================================

SOURCE_SUMMARY_TEMPLATE = """---
type: source-summary
source_url: {url}
title: {title}
source_type: {source_type}
date_ingested: {date}
---

# {title}

## 核心论点
{claims}

## 关键信息
{key_info}

## 标签
{tags}
"""

ENTITY_PAGE_TEMPLATE = """---
type: entity
name: {name}
entity_type: {type}
version: {version}
license: {license}
---

# {name}

## 概述
{description}

## 详细信息
{details}
"""

CONCEPT_PAGE_TEMPLATE = """---
type: concept
name: {name}
source: {source}
---

# {name}

## 定义
{definition}

## 关键要点
{points}
"""

COMPARISON_PAGE_TEMPLATE = """---
type: comparison
title: {title}
compared_items: {items}
---

# {title}

## 对比矩阵
{matrix}

## 推荐
{recommendation}
"""

# ============================================================
# Comparison routing table
# ============================================================

COMPARISON_TYPES = {
    ContentType.TOOL_EXTENSION,
    ContentType.TOOL_REVIEW,
    ContentType.ARCHITECTURE_ANALYSIS,
    ContentType.AI_AGENT,
    ContentType.SECURITY_RESEARCH,
}


class LLMWikiIngest:
    """LLM Wiki 摄入管道 — 源→摘要→概念→实体→对比→ZK候选

    所有产出路径使用人类指定仓库的绝对路径。
    写入磁盘前检查仓库是否已配置，未配置则拒绝写入。
    """

    def __init__(self, config: Optional[CTWConfig] = None,
                 template_engine: Optional[TemplateEngine] = None,
                 llm_enabled: bool = True):
        self.config = config or CTWConfig()
        self.template_engine = template_engine or TemplateEngine()
        self.llm_enabled = llm_enabled and _get_llm_client is not None

    def _llm_generate(self, system_prompt: str, user_prompt: str,
                      max_tokens: int = 4096) -> Optional[str]:
        """Generate content via LLM. Returns None if LLM is unavailable."""
        if not self.llm_enabled:
            return None
        try:
            client = _get_llm_client()
            return client.generate(system_prompt, user_prompt, max_tokens=max_tokens)
        except Exception:
            return None

    def _make_path(self, category: str, filename: str, ext: str = ".md") -> str:
        """构建仓库下的绝对路径。"""
        base = self.config.get_output_path(category)
        return str(base / (filename + ext))

    def _slug(self, text: str) -> str:
        """生成安全的文件名 slug。"""
        if not text:
            return "untitled"
        slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff_-]", "-", text)
        slug = re.sub(r"-{2,}", "-", slug)
        return slug[:80].strip("-").lower()

    def ingest(
        self,
        source: SourceInput,
        classify_result: ClassifyResult,
        level_result: LevelResult,
        auto_write: bool = False,
    ) -> IngestResult:
        """全管道摄入: 根据内容类型和深度等级生成不同的输出组合并写入磁盘。

        生成规则:
        - 所有类型 → source_summary + zk_candidates
        - TOOL_EXTENSION/TOOL_REVIEW/ARCHITECTURE_ANALYSIS/AI_AGENT → entity
        - ARCHITECTURE_ANALYSIS/PAPER_REVIEW → concepts
        - comparison 类型 → comparison_pages

        Args:
            source: 资料输入
            classify_result: 分类结果
            level_result: 深度路由结果
            auto_write: True → 立即写盘; False → 只生成不写盘（需调用 write_outputs()）

        Returns:
            IngestResult 含所有生成内容和实际写入的文件路径

        路径使用人类指定仓库的绝对路径。
        如果仓库未配置，output_files 为空列表，content 仍会生成。
        """
        result = IngestResult()
        have_repo = self.config.has_repository
        slug = self._slug(source.title)

        # 1. Source summary — always generated
        summary = self.generate_source_summary(source, classify_result=classify_result)
        result.source_summary = summary
        if have_repo:
            result.output_files.append(self._make_path("sources", slug))

        # 2. Entity pages — for tool/architecture/agent types
        if self._needs_entity(classify_result.content_type, source):
            entity = self.generate_entity_page(source.title, {
                "name": source.title,
                "type": classify_result.content_type.value,
                "version": "unknown",
                "license": "unknown" if source.source_type not in ("repo", "code") else "varies",
                "description": source.description or source.title,
                "details": source.content[:500] if source.content else "",
            })
            result.entity_pages.append(entity)
            if have_repo:
                result.output_files.append(self._make_path("entities", slug))

        # 3. Concept pages — architecture and paper types
        if self._needs_concepts(classify_result.content_type, source):
            concepts = self._extract_concepts(source)
            for concept in concepts:
                page = self.generate_concept_page(concept, {
                    "definition": concept,
                    "points": "从 " + (source.title or "source") + " 提取",
                })
                result.concept_pages.append(page)
                if have_repo:
                    concept_slug = self._slug(concept)
                    result.output_files.append(self._make_path("concepts", concept_slug))

        # 4. Comparison pages — when applicable
        if self.should_generate_comparison(classify_result):
            cpages = self.generate_comparison_pages(source, classify_result)
            result.comparison_pages.extend(cpages)
            if have_repo:
                for i, _ in enumerate(cpages, 1):
                    result.output_files.append(
                        self._make_path("comparisons", f"{slug}-v{i}")
                    )

        # 5. ZK candidates — from source content
        if source.content:
            zk_raw = self.extract_zk_candidates(source.content, min_confidence=0.6)
            result.zk_candidates = [z.title for z in zk_raw]
            if have_repo and zk_raw:
                for zk in zk_raw:
                    zk_path = self._make_path("zk", zk.id)
                    result.output_files.append(zk_path)

        # 6. Human feedback check
        result.human_feedback_required = (
            classify_result.confidence < 0.5
            or level_result.confidence < 0.5
            or not source.content
        )

        # 7. Auto-write to disk if requested
        result.written_files = []
        if auto_write and have_repo:
            result.written_files = self.write_outputs(result)

        return result

    def write_outputs(self, result: IngestResult) -> list[str]:
        """将 IngestResult 中的所有产出写入磁盘。

        按 output_files 的顺序严格对应写入：
          [0] source_summary
          [1..n_entity] entity_pages
          [n_entity+1 .. n_entity+n_concept] concept_pages
          [...] comparison_pages
          [...] zk notes

        Args:
            result: ingest() 返回的结果

        Returns:
            实际写入的文件路径列表

        Raises:
            RuntimeError: 仓库路径未配置
        """
        repo = self.config.require_repository()
        written = []

        # Ensure directory structure
        for cat in ("sources", "entities", "concepts", "comparisons"):
            os.makedirs(repo / "wiki" / cat, exist_ok=True)
        os.makedirs(repo / "zettelkasten" / "2-permanent", exist_ok=True)

        idx = 0

        # Source summary → output_files[0]
        if result.source_summary and idx < len(result.output_files):
            p = result.output_files[idx]
            self._write_file(p, result.source_summary)
            written.append(p)
            idx += 1

        # Entity pages
        for entity in result.entity_pages:
            if idx < len(result.output_files):
                p = result.output_files[idx]
                self._write_file(p, entity)
                written.append(p)
                idx += 1

        # Concept pages
        for concept in result.concept_pages:
            if idx < len(result.output_files):
                p = result.output_files[idx]
                self._write_file(p, concept)
                written.append(p)
                idx += 1

        # Comparison pages
        for comp in result.comparison_pages:
            if idx < len(result.output_files):
                p = result.output_files[idx]
                self._write_file(p, comp)
                written.append(p)
                idx += 1

        # ZK notes
        for zk_title in result.zk_candidates:
            if idx < len(result.output_files):
                p = result.output_files[idx]
                zk_content = f"---\ntype: zk-note\ntitle: {zk_title}\n---\n\n# {zk_title}\n"
                self._write_file(p, zk_content)
                written.append(p)
                idx += 1

        return written

    @staticmethod
    def _write_file(path: str, content: str) -> None:
        """写入文件，自动创建父目录。"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    # ---- Source Summary ----

    def generate_source_summary(self, source: SourceInput,
                                 classify_result: Optional[ClassifyResult] = None) -> str:
        """生成源摘要页，优先使用 LLM 生成分析内容，回退到模板渲染。"""
        tags = self._guess_tags(source)
        value_questions_text = ""
        if classify_result and classify_result.value_questions:
            q_lines = [f"- **{q.question}** [{q.priority}]" for q in classify_result.value_questions]
            value_questions_text = "\n".join(q_lines)

        content_type = classify_result.content_type_name if classify_result else "unknown"

        # Try LLM-powered analysis
        llm_analysis = self._llm_generate(
            system_prompt=(
                "You are a technical analyst writing structured markdown for a knowledge wiki. "
                "Write in Chinese. Be concise and factual."
            ),
            user_prompt=(
                f"Analyze the following content about [{source.title}]. "
                f"Content type: {content_type}. Source type: {source.source_type}.\n\n"
                f"URL: {source.url}\n"
                f"Description: {source.description or 'N/A'}\n"
                f"Content:\n{(source.content or '')[:3000]}\n\n"
                "Write these sections in markdown:\n"
                "## 核心论点\n"
                "- 2-3 key claims/arguments as bullet points\n"
                "## 摘要\n"
                "- 2-3 paragraph summary\n"
                "## 关键概念\n"
                "- List 2-5 key concepts with brief definitions"
            ),
            max_tokens=2048,
        )

        data = {
            "title": source.title or "Untitled",
            "source_file": source.url,
            "source_type": source.source_type or "unknown",
            "author": "",
            "date_read": time.strftime("%Y-%m-%d"),
            "claim_1": source.description or "暂无摘要",
            "claim_2": "",
            "claim_3": "",
            "line_range": "",
            "provenance_state": "extracted",
            "confidence": str(classify_result.confidence) if classify_result else "0.7",
        }

        template = self.template_engine.read_template("source_summary")
        rendered = self.template_engine.render(template, data)

        # Inject LLM analysis or fallback content
        if llm_analysis:
            rendered += "\n" + llm_analysis + "\n"
        else:
            rendered += "\n## 摘要\n\n" + (source.description or "暂无摘要") + "\n"

        # Append value questions section if present
        if value_questions_text:
            rendered += f"\n## 价值问题\n\n{value_questions_text}\n"

        # Append ZK candidates
        rendered += "\n## ZK 原子化候选清单\n\n"
        for candidate in self.extract_zk_candidates(source.content or "", min_confidence=0.5):
            rendered += f"- [ ] {candidate.title}\n"

        return rendered

    # ---- Entity Page ----

    def generate_entity_page(self, name: str, data: dict) -> str:
        """生成实体页。LLM 生成分析内容，模板提供框架。"""
        entity_type = data.get("type", "unknown")
        description = data.get("description", "")

        llm_content = self._llm_generate(
            system_prompt="You are a technical analyst. Write in Chinese. Be concise.",
            user_prompt=(
                f"Write a knowledge base entry for the entity [{name}] "
                f"(type: {entity_type}). "
                f"Description: {description}\n\n"
                "Include these sections:\n"
                "## 概述\n- What it is, what it does\n"
                "## 核心能力\n- 3-5 key capabilities\n"
                "## 技术架构\n- Technical architecture highlights\n"
                "## 使用场景\n- 2-3 use cases\n"
                "## 相关实体\n- Link to related tools/frameworks"
            ),
            max_tokens=2048,
        )

        template = self.template_engine.read_template("entity")
        base = self.template_engine.render(template, {
            "title": name,
            "entity_type": entity_type,
        })
        if llm_content:
            base += "\n" + llm_content + "\n"
        return base

    # ---- Concept Pages ----

    def generate_concept_pages(self, concepts: list[str], data: dict) -> list[str]:
        """生成概念页面列表。"""
        pages = []
        for concept in concepts:
            pages.append(self.generate_concept_page(concept, data))
        return pages

    def generate_concept_page(self, name: str, data: dict) -> str:
        """生成单个概念页，使用 TemplateEngine 渲染。"""
        template = self.template_engine.read_template("concept")
        return self.template_engine.render(template, {
            "title": name,
            "domain": data.get("source", ""),
        })

    # ---- Comparison Pages ----

    def generate_comparison_pages(
        self, source: SourceInput, classify_result: ClassifyResult
    ) -> list[str]:
        """生成对比页面。LLM 生成对比分析，模板提供框架。"""
        title = source.title or "Unknown"

        llm_content = self._llm_generate(
            system_prompt="You are a technical analyst. Write in Chinese. Be objective.",
            user_prompt=(
                f"Compare [{title}] with similar alternatives. "
                f"Content type: {classify_result.content_type_name}. "
                f"Description: {source.description or 'N/A'}\n"
                f"Content: {(source.content or '')[:2000]}\n\n"
                "Include:\n"
                "## 对比维度\n"
                "- Comparison dimensions table\n"
                "## 相似点\n- Commonalities\n"
                "## 差异点\n- Key differences\n"
                "## 选择建议\n- When to choose what\n"
                "## 推荐决策矩阵\n- Decision matrix table"
            ),
            max_tokens=2048,
        )

        template = self.template_engine.read_template("comparison")
        rendered = self.template_engine.render(template, {
            "A": title,
            "B": "Alternatives",
            "title": f"{title} vs Alternatives",
            "scenario_1": "use case 1",
            "scenario_2": "use case 2",
            "scenario_3": "use case 3",
        })
        if llm_content:
            rendered += "\n" + llm_content + "\n"
        return [rendered]

    def should_generate_comparison(self, classify_result: ClassifyResult) -> bool:
        """判断是否需要生成对比页面。"""
        return classify_result.content_type in COMPARISON_TYPES

    # ---- ZK Candidates ----

    def extract_zk_candidates(
        self, content: str, min_confidence: float = 0.6
    ) -> list[ZkCandidate]:
        """从内容中提取 ZK 永久笔记候选。

        优先解析 "## ZK Atomic Candidates" 节的 - [ ] 列表；
        后备方案：解析 "## Other Content" 节以外的段落首句。
        """
        candidates = []

        # 尝试匹配 ZK Atomic Candidates 节
        zk_pattern = r"##\s*ZK\s+Atomic\s+Candidates\s*\n+(.*?)(?=\n##\s|\Z)"
        match = re.search(zk_pattern, content, re.DOTALL | re.IGNORECASE)

        if match:
            section = match.group(1)
            items = re.findall(r"- \[[ x]\]\s*(.+)", section)
            for item in items:
                item = item.strip()
                if not item:
                    continue
                cid = "zk_" + hashlib.md5(item.encode()).hexdigest()[:8]
                # Assign confidence based on specificity (heuristic)
                conf = 0.7 + min(0.3, len(item) / 200.0)
                candidates.append(ZkCandidate(
                    id=cid,
                    title=item[:120],
                    abstract=item,
                    confidence=conf,
                    priority=3,
                ))

        # Fallback: extract sentences from main content (before ZK section)
        if not candidates:
            # Clean content — remove headers, code blocks
            clean = re.sub(r"```.*?```", "", content, flags=re.DOTALL)
            clean = re.sub(r"^#.*$", "", clean, flags=re.MULTILINE)
            clean = re.sub(r"^\s*- \[[ x]\].*$", "", clean, flags=re.MULTILINE)
            sentences = re.findall(r"[A-Za-z\u4e00-\u9fff][^.!?。！？\n]{20,120}[.!?。！？]", clean)
            for i, sent in enumerate(sentences[:5]):
                sent = sent.strip()
                if not sent or len(sent) < 10:
                    continue
                cid = "zk_" + hashlib.md5(sent.encode()).hexdigest()[:8]
                conf = 0.5 + min(0.3, len(sent) / 200.0)
                candidates.append(ZkCandidate(
                    id=cid,
                    title=sent[:120],
                    abstract=sent,
                    confidence=conf,
                    priority=4,
                ))

        # Confidence filter
        return [c for c in candidates if c.confidence >= min_confidence]

    # ---- Internal Helpers ----

    def _needs_entity(self, content_type: ContentType, source: SourceInput) -> bool:
        """判断是否需要生成实体页。"""
        return content_type in {
            ContentType.TOOL_EXTENSION,
            ContentType.TOOL_REVIEW,
            ContentType.ARCHITECTURE_ANALYSIS,
            ContentType.AI_AGENT,
            ContentType.SECURITY_RESEARCH,
        }

    def _needs_concepts(self, content_type: ContentType, source: SourceInput) -> bool:
        """判断是否需要生成概念页。"""
        return content_type in {
            ContentType.ARCHITECTURE_ANALYSIS,
            ContentType.PAPER_REVIEW,
        }

    def _extract_concepts(self, source: SourceInput) -> list[str]:
        """从源内容中提取概念关键词。"""
        concepts = []
        if source.content:
            # 从 ## Entities / ## Concepts 节提取
            entity_match = re.findall(r"###\s+(.+)", source.content)
            concepts.extend([m.strip() for m in entity_match[:5]])

        if not concepts:
            # Fallback: use title and description
            if source.title:
                concepts.append(source.title)
            if source.description:
                # Take first phrase
                concepts.append(source.description[:50])

        return concepts or ["通用概念"]

    def _guess_tags(self, source: SourceInput) -> list[str]:
        """从源内容猜测标签。"""
        tags = []
        if source.source_type:
            tags.append(source.source_type)
        return tags or ["general"]
