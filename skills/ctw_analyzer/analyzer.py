"""
CTW Analyzer — 智能交互入口

实现 `/ctw_ana` 命令的智能分析协议：
- 从人类输入中提取 URL 和意图
- 自动分诊（多源识别 → 分类 → 深度决策）
- 进度反馈（阶段化输出）
- 智能追问（信息不足时请求补充）
- 按价值自动推进或等待人类决策

设计哲学：人类只需说"帮我分析这个"，系统自动判断要处理什么、
处理到哪一层、是否需要追加信息。
"""

import sys
import os
import re
import json
import time
from dataclasses import dataclass, field
from typing import Optional

# Bootstrap paths — auto-detect project root relative to this file
_CTW_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for p in [
    _CTW_ROOT,
    os.path.join(_CTW_ROOT, "lib"),
    os.path.join(_CTW_ROOT, "skills"),
    os.path.join(_CTW_ROOT, "skills", "ctw_classify"),
    os.path.join(_CTW_ROOT, "skills", "ctw_infolevel"),
    os.path.join(_CTW_ROOT, "skills", "ctw_ingest"),
    os.path.join(_CTW_ROOT, "skills", "ctw_pipeline"),
]:
    if p not in sys.path:
        sys.path.insert(0, p)

from ctw_state import RunStore
from ctw_types import (
    SourceInput, ClassifyResult, ContentType, InfoLevel,
    LevelResult, PipelineResult, GateTrigger, GateStatus, GateName,
    IngestResult, ZkCandidate, ValueQuestion,
)
from classifier import TaxonomyClassifier
from router import InfoLevelRouter
from ingest import LLMWikiIngest

# Try importing ResourceFetcher
_RESOURCE_FETCHER_AVAILABLE = False
try:
    sys.path.insert(0, os.path.join(_CTW_ROOT, "skills", "ctw_fetch"))
    from fetcher import ResourceFetcher
    _RESOURCE_FETCHER_AVAILABLE = True
except ImportError:
    ResourceFetcher = None

# ============================================================
# Protocol Types
# ============================================================

@dataclass
class AnalyzedSource:
    """单个被分析的资料"""
    url: str
    title: str = ""
    description: str = ""
    content: str = ""
    source_type: str = ""       # 自动推断: repo / pdf / article / video / url
    # 管线产出
    classify: Optional[ClassifyResult] = None
    level: Optional[LevelResult] = None
    ingest: Optional[IngestResult] = None
    # 元数据
    auto_depth: InfoLevel = InfoLevel.L0      # 系统自动决定的深度
    needs_more_info: bool = False
    missing_fields: list[str] = field(default_factory=list)
    quality_score: float = 0.0   # 0-1，信息完整度
    errors: list[str] = field(default_factory=list)


@dataclass
class AnalysisProgress:
    """分析进度报告"""
    stage: str = "init"          # init / parsing / classifying / routing / ingesting / done
    total_sources: int = 0
    processed: int = 0
    current_source: str = ""
    messages: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)   # 系统自动决策记录
    human_questions: list[str] = field(default_factory=list)  # 需要人类回答的问题


@dataclass
class AnalysisResult:
    """分析完整结果"""
    sources: list[AnalyzedSource] = field(default_factory=list)
    progress: AnalysisProgress = field(default_factory=AnalysisProgress)
    pipeline_results: list[PipelineResult] = field(default_factory=list)
    summary: str = ""
    recommendations: list[str] = field(default_factory=list)
    followup_questions: list[str] = field(default_factory=list)
    action_required: bool = False     # 是否需要人类介入
    total_time_ms: float = 0.0


# ============================================================
# URL / Source Extraction
# ============================================================

# URL 匹配模式
# URL 匹配模式（支持中文标点结尾清除）
_URL_EXCLUDE = "\\s<>\"{}|\\\\^`\\[\\]"
_URL_EXCLUDE += "\uff0c\u3001\u3002\uff01\uff1f\uff1b\uff1a"  # ，。、！？；：
_URL_EXCLUDE += "\u201c\u201d\uff08\uff09"  # ""（）
URL_PATTERN = re.compile(
    r'(https?://[^' + _URL_EXCLUDE + r']+)',
    re.IGNORECASE
)

# 特殊域名→source_type 映射
DOMAIN_TYPE_MAP = {
    'github.com': 'repo',
    'arxiv.org': 'pdf',
    'youtube.com': 'video',
    'youtu.be': 'video',
    'bilibili.com': 'video',
    'v2ex.com': 'article',
    'zhihu.com': 'article',
    'sspai.com': 'article',
    'medium.com': 'article',
    'reddit.com': 'article',
    'twitter.com': 'article',
    'x.com': 'article',
    'npmjs.com': 'tool',
    'pypi.org': 'tool',
    'crates.io': 'tool',
    'huggingface.co': 'model',
}

# 标题相关的引导词（用于从prompt中提取标题）
TITLE_HINTS = [
    '标题是', '标题：', 'title:', '题目是', '这篇文章', '这个视频',
    '这个项目', '这个工具', '这篇论文', '这个仓库',
]


def extract_urls(text: str) -> list[str]:
    """从文本中提取所有 URL"""
    return [m.group(1).rstrip('.,;:!?）)') for m in URL_PATTERN.finditer(text)]


def infer_source_type(url: str) -> str:
    """从 URL 推断 source_type"""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    domain = parsed.hostname or ""
    # 精确匹配
    for key, stype in DOMAIN_TYPE_MAP.items():
        if key in domain:
            return stype
    # 路径启发式
    path = parsed.path.lower()
    if path.endswith('.pdf'):
        return 'pdf'
    # 默认
    return 'article'


def extract_title_from_prompt(prompt: str, urls: list[str]) -> str:
    """从人类 prompt 中提取资料标题"""
    # 去掉 URL
    cleaned = prompt
    for url in urls:
        cleaned = cleaned.replace(url, '')
    cleaned = cleaned.strip().strip('.,;:!?，。；：！？、""''（）')
    # 去掉引导词
    for hint in TITLE_HINTS:
        if hint.lower() in cleaned.lower():
            idx = cleaned.lower().find(hint.lower())
            cleaned = cleaned[idx + len(hint):].strip().strip('.,;:!?，。；：！？、""''（）\n')
    # 如果有残余文字，用它做标题
    if cleaned:
        # 取第一行/第一句
        first_line = cleaned.split('\n')[0].strip()
        if len(first_line) > 100:
            first_line = first_line[:100] + '...'
        return first_line
    return ""


def analyze_prompt(prompt: str) -> tuple[list[str], str, str]:
    """
    解析人类输入，提取 URL、意图文本、剩余描述。

    Returns:
        (urls, intent_text, description)
        - urls: 提取到的 URL 列表
        - intent_text: 去除 URL 后的纯文本意图
        - description: 如果有额外描述则提取
    """
    urls = extract_urls(prompt)
    # 移除 URL 得到意图文本
    intent = prompt
    for url in urls:
        intent = intent.replace(url, '')
    intent = intent.strip().strip('.,;:!?，。；：！？、""''（）\n')

    # 如果意图文本以 "/ctw_ana" 开头，去掉它
    intent = re.sub(r'^[/\s]*ctw_ana\s*', '', intent, flags=re.IGNORECASE).strip()

    return urls, intent, ""


# ============================================================
# Quality Assessment
# ============================================================

def assess_source_quality(source: AnalyzedSource) -> float:
    """评估资料信息完整度 0-1"""
    score = 0.0
    if source.url:
        score += 0.3
    if source.title:
        score += 0.3
    if source.description:
        score += 0.1
    if source.content:
        score += 0.2
    if source.source_type:
        score += 0.1
    return min(score, 1.0)


def identify_missing_fields(source: AnalyzedSource) -> list[str]:
    """识别缺失的关键字段"""
    missing = []
    if not source.title:
        missing.append("title")
    if not source.content and not source.description:
        missing.append("content")
    return missing


# ============================================================
# Smart Depth Decision
# ============================================================

def auto_decide_depth(classify_result: ClassifyResult, quality: float) -> tuple[InfoLevel, str]:
    """
    智能决定处理深度。

    规则：
    - quality < 0.3 → 最多 L0（信息太少，不值得深入）
    - quality < 0.6 → 最多 L1（信息不够，不做深度分析）
    - confidence >= 0.85 → 可以按建议深度全量处理
    - confidence < 0.85 → 降一级（分类不确定时不深挖）
    - 特例：安全研究永远 L1（安全信息优先处理）
    - 特例：技术新闻永远 L0（时效新闻无需深挖）
    """
    ct = classify_result.content_type
    suggested = classify_result.suggested_level
    confidence = classify_result.confidence

    # 硬规则
    if ct == ContentType.TECH_NEWS:
        return InfoLevel.L0, "技术新闻 → 速览模式 (L0)"
    if ct == ContentType.SECURITY_RESEARCH:
        return InfoLevel.L1, "安全研究 → 优先处理 (L1)"

    if quality < 0.3:
        # 只有 URL，没有标题/内容 → 只能 L0
        return InfoLevel.L0, "信息太少（仅有链接），执行速览 (L0)，可稍后补充信息后升级"

    # 按置信度和质量降级
    levels = [InfoLevel.L0, InfoLevel.L1, InfoLevel.L2, InfoLevel.L3, InfoLevel.L4]
    target_idx = levels.index(suggested)

    if confidence < 0.85:
        target_idx = max(0, target_idx - 1)  # 降一级
    if quality < 0.6 and target_idx > 1:
        target_idx = 1  # 信息不足时最高 L1

    return levels[target_idx], f"自动决策: 置信度={confidence:.0%}, 完整度={quality:.0%} → {levels[target_idx].value}"


# ============================================================
# CTW Analyzer — 主控制器
# ============================================================

class CTWAnalyzer:
    """CTW 智能分析入口

    用法:
        analyzer = CTWAnalyzer()
        result = analyzer.analyze("帮我分析 https://github.com/user/repo 这个 MCP 工具")

    协议:
        1. 解析输入 → 提取 URL + 意图
        2. 为每个 URL 创建 source → 评估质量
        3. 质量不足 → 返回追问（需要人类补充标题/内容）
        4. 质量足够 → 执行管线 → 返回结果
        5. 进度在每个阶段更新
    """

    def __init__(self):
        self.classifier = TaxonomyClassifier()
        self.router = InfoLevelRouter()
        self.ingest = LLMWikiIngest()
        # In-memory state for /status and /history (Slice 5)
        self._runs: list[dict] = []
        self._current_run: dict = {}
        # Persistence + pattern analysis
        self._store = RunStore()
        self._patterns = None  # lazy init via _get_patterns()

    def _get_patterns(self):
        if self._patterns is None:
            from patterns import PatternAnalyzer
            self._patterns = PatternAnalyzer(self._store)
        return self._patterns

    def _get_fetcher(self):
        """Lazy fetcher creation for testability."""
        if ResourceFetcher:
            return ResourceFetcher()
        return None

    # ============================================================
    # Phase 1: assess() — fetch + classify + Assessment (Slice 3)
    # ============================================================

    def assess(self, prompt: str) -> dict:
        """Fetch, classify, route and return an Assessment dict for human review.

        Returns a dict with the PRD Assessment shape:
            content_type, content_type_name, confidence,
            recommended_depth, level_name, source_type,
            direction_summary, direction_reason, value_questions
        """
        urls = extract_urls(prompt)
        if not urls:
            return {
                "content_type": "", "content_type_name": "",
                "confidence": 0.0, "recommended_depth": "",
                "level_name": "", "source_type": "",
                "direction_summary": "", "direction_reason": "",
                "value_questions": [], "action_required": True,
                "needs_more_info": True,
            }

        url = urls[0]
        source_type = infer_source_type(url)

        # Fetch with error fallback
        source = None
        needs_more_info = False
        fetcher = self._get_fetcher()
        if fetcher:
            try:
                source = fetcher.fetch(url)
                if not source.title and not source.content:
                    needs_more_info = True
            except Exception:
                # Try generic web page fetch as fallback
                try:
                    source = fetcher.fetch(url, source_type=source_type)
                    if not source.title and not source.content:
                        needs_more_info = True
                except Exception:
                    needs_more_info = True
        else:
            needs_more_info = True

        if source is None:
            source = SourceInput(url=url, source_type=source_type)
            needs_more_info = True

        # Classify
        classify_result = self.classifier.classify(source)
        source_type = source.source_type or source_type

        # Route depth
        level_result = self.router.route(classify_result)

        # Direction recommendation
        direction = self._direction_for(classify_result, level_result)

        result = {
            "content_type": classify_result.content_type.value,
            "content_type_name": classify_result.content_type_name,
            "confidence": classify_result.confidence,
            "recommended_depth": level_result.level.value,
            "level_name": level_result.level_name,
            "source_type": source_type,
            "direction_summary": direction["summary"],
            "direction_reason": direction["reason"],
            "value_questions": [
                {"id": q.id, "question": q.question, "priority": q.priority}
                for q in classify_result.value_questions
            ],
            "url": url,
            "needs_more_info": needs_more_info,
        }
        return result

    def _direction_for(self, classify_result, level_result) -> dict:
        """Generate direction recommendation based on content type and depth."""
        ct = classify_result.content_type
        level = level_result.level

        if ct == ContentType.SECURITY_RESEARCH:
            return {"summary": "安全优先 — 立即深度处理",
                    "reason": "安全研究需要紧急评估"}
        elif ct == ContentType.TECH_NEWS:
            return {"summary": "速览归档",
                    "reason": "技术新闻时效性强，快速记录要点即可"}
        elif level in (InfoLevel.L3, InfoLevel.L4):
            return {"summary": "深度处理",
                    "reason": f"内容复杂度高，建议 {level.value} 级别深入分析"}
        elif level == InfoLevel.L2:
            return {"summary": "标准处理",
                    "reason": "适中的分析深度，产出实体+对比页"}
        elif level == InfoLevel.L1:
            return {"summary": "快速处理",
                    "reason": "工具评测/教程类，产出摘要+ZK候选"}
        else:
            return {"summary": "速览",
                    "reason": "低复杂度内容，仅记录基本信息"}

    # ============================================================
    # Phase 2: plan() — ProcessingPlan + deviations (Slice 4)
    # ============================================================

    def plan(self, assessment: dict, human_feedback: str = "") -> dict:
        """Generate a ProcessingPlan from an Assessment and human feedback.

        Records WorkflowDeviation if human overrides any parameter.
        """
        from ctw_types import WorkflowDeviation, ProcessingPlan

        deviations = []
        status = "approved"

        # Parse human feedback
        feedback_lower = human_feedback.strip().lower() if human_feedback else ""

        # "cancel" or no human feedback → just accept
        if not feedback_lower or feedback_lower in ("ok", "looks good", "approve", "yes", "好", "可以"):
            pass  # No deviations
        elif "cancel" in feedback_lower:
            status = "cancelled"
        else:
            # Check for depth override: "L3", "go deeper", "change depth to L3"
            depth_match = re.search(r"L([0-4])", feedback_lower, re.IGNORECASE)
            if depth_match:
                new_depth = f"L{depth_match.group(1)}"
                if new_depth != assessment.get("recommended_depth", ""):
                    deviations.append(WorkflowDeviation(
                        axis="depth",
                        original_value=assessment.get("recommended_depth", ""),
                        new_value=new_depth,
                        reason=human_feedback,
                    ))
                    assessment = {**assessment, "recommended_depth": new_depth}

            # Check for type override: "type: tool-review", "this is a paper review"
            for ct_name in ["tool-extension", "tool-review", "practice-tutorial",
                           "architecture-analysis", "paper-review", "tech-news",
                           "experience-share", "spec-standard", "security-research", "ai-agent"]:
                if ct_name in feedback_lower:
                    if ct_name != assessment.get("content_type", ""):
                        deviations.append(WorkflowDeviation(
                            axis="type",
                            original_value=assessment.get("content_type", ""),
                            new_value=ct_name,
                            reason=human_feedback,
                        ))
                        assessment = {**assessment, "content_type": ct_name}
                    break

            # Check for scope override: "skip comparison"
            if "skip comparison" in feedback_lower or "no comparison" in feedback_lower:
                deviations.append(WorkflowDeviation(
                    axis="scope",
                    original_value="comparison",
                    new_value="skip_comparison",
                    reason=human_feedback,
                ))

        # ── Pattern analysis: auto-apply learned preferences ──
        suggestions = {}
        if not deviations:  # only auto-apply when human didn't already override
            try:
                pat = self._get_patterns()
                suggestions = pat.get_suggestions(
                    url=assessment.get("url", ""),
                    content_type=assessment.get("content_type", ""),
                    recommended_depth=assessment.get("recommended_depth", ""),
                )
                # Auto-apply type correction
                if suggestions.get("type_auto_apply") and suggestions.get("type_suggestion"):
                    new_type = suggestions["type_suggestion"]
                    if new_type != assessment.get("content_type", ""):
                        deviations.append(WorkflowDeviation(
                            axis="type",
                            original_value=assessment.get("content_type", ""),
                            new_value=new_type,
                            reason=f"learned: user corrects to {new_type} "
                                   f"({suggestions['type_confidence']}x)",
                            source="learned",
                        ))
                        assessment = {**assessment, "content_type": new_type}
                # Auto-apply depth preference
                if suggestions.get("depth_auto_apply") and suggestions.get("depth_suggestion"):
                    new_depth = suggestions["depth_suggestion"]
                    if new_depth != assessment.get("recommended_depth", ""):
                        deviations.append(WorkflowDeviation(
                            axis="depth",
                            original_value=assessment.get("recommended_depth", ""),
                            new_value=new_depth,
                            reason=f"learned: user prefers {suggestions['depth_direction']} "
                                   f"({suggestions['depth_confidence']}x)",
                            source="learned",
                        ))
                        assessment = {**assessment, "recommended_depth": new_depth}
            except Exception:
                pass  # pattern analysis is advisory, never block

        # Build execution steps
        steps = [
            {"step": 1, "action": "fetch", "description": f"Fetch from {assessment.get('url', 'unknown')}"},
            {"step": 2, "action": "classify", "description": f"Classify as {assessment.get('content_type_name', 'unknown')}"},
            {"step": 3, "action": "route", "description": f"Route to depth {assessment.get('recommended_depth', 'L1')}"},
            {"step": 4, "action": "ingest", "description": "Generate wiki artifacts + ZK candidates"},
        ]

        # Expected output counts
        ct = assessment.get("content_type", "")
        expected = {"source_summary": 1, "zk_candidates": 2}
        if ct in ("tool-extension", "tool-review", "architecture-analysis", "ai-agent", "security-research"):
            expected["entity_pages"] = 1
        if ct in ("architecture-analysis", "paper-review"):
            expected["concept_pages"] = 1
        if ct in ("tool-extension", "tool-review", "architecture-analysis", "ai-agent", "security-research"):
            expected["comparison_pages"] = 1

        # Remove skipped items
        for d in deviations:
            if d.axis == "scope" and d.new_value == "skip_comparison":
                expected.pop("comparison_pages", None)
                steps = [s for s in steps if s["action"] != "ingest"] + [
                    {"step": 4, "action": "ingest", "description": "Generate wiki artifacts (no comparison) + ZK candidates"}
                ]

        return {
            "content_type_name": assessment.get("content_type_name", ""),
            "content_type": assessment.get("content_type", ""),
            "confidence": assessment.get("confidence", 0.0),
            "recommended_depth": assessment.get("recommended_depth", ""),
            "level_name": assessment.get("level_name", ""),
            "source_type": assessment.get("source_type", ""),
            "direction_summary": assessment.get("direction_summary", ""),
            "direction_reason": assessment.get("direction_reason", ""),
            "value_questions": assessment.get("value_questions", []),
            "execution_steps": steps,
            "expected_outputs": expected,
            "deviations": deviations,
            "status": status,
            "suggestions": {k: v for k, v in suggestions.items()
                           if v and k not in ("type_auto_apply", "depth_auto_apply")},
        }

    # ============================================================
    # Phase 3: execute() — pipeline execution + ZK approval (Slice 5)
    # ============================================================

    def execute(self, plan: dict, auto_write: bool = True,
                zk_approvals: list = None) -> dict:
        """Execute an approved ProcessingPlan through the full pipeline.

        Args:
            plan: ProcessingPlan dict from plan()
            auto_write: If True, write wiki pages to artifact repo
            zk_approvals: List of ZK candidate indices to approve (0-based),
                          "all", "none", or list of merge targets like {"3": "existing-id"}

        Returns:
            PipelineResult dict with status, written files, ZK notes, etc.
        """
        run_id = time.strftime("%Y%m%d-%H%M%S")
        self._current_run = {"run_id": run_id, "status": "in_progress",
                             "started": time.strftime("%Y-%m-%dT%H:%M:%S")}

        errors = []
        url = plan.get("url", "")

        # Fetch
        source = None
        fetcher = self._get_fetcher()
        if fetcher and url:
            try:
                source = fetcher.fetch(url)
            except Exception as e:
                errors.append(f"Fetch failed: {e}")
                source = SourceInput(url=url)

        if source is None:
            source = SourceInput(url=url)

        # Classify
        classify_result = None
        try:
            classify_result = self.classifier.classify(source)
        except Exception as e:
            errors.append(f"Classify failed: {e}")

        if classify_result is None:
            classify_result = ClassifyResult(content_type=ContentType.UNKNOWN)

        # Route
        level_result = None
        try:
            level_result = self.router.route(classify_result)
        except Exception as e:
            errors.append(f"Route failed: {e}")
            level_result = LevelResult(level=InfoLevel.L0)

        # Ingest
        ingest_result = None
        try:
            ingest_result = self.ingest.ingest(source, classify_result, level_result,
                                               auto_write=auto_write)
        except Exception as e:
            errors.append(f"Ingest failed: {e}")
            ingest_result = IngestResult()

        # ZK approval handling
        written_zk = []
        zk_candidates = []
        if ingest_result and ingest_result.zk_candidates:
            from ctw_types import ZkCandidate
            for i, title in enumerate(ingest_result.zk_candidates):
                zk = ZkCandidate(title=title, abstract=title)
                zk_candidates.append(zk)

            # Filter by approvals
            if zk_approvals is None:
                # No human feedback yet — all pending
                pass
            elif zk_approvals == "all":
                for zk in zk_candidates:
                    written_zk.append(zk)
            elif zk_approvals == "none":
                pass  # Write nothing
            elif isinstance(zk_approvals, list):
                for idx in zk_approvals:
                    if isinstance(idx, int) and 0 <= idx < len(zk_candidates):
                        written_zk.append(zk_candidates[idx])
                    elif isinstance(idx, dict):
                        # Merge: {"3": "existing-id"}
                        for cif, tid in idx.items():
                            ci = int(cif)
                            if 0 <= ci < len(zk_candidates):
                                zk_candidates[ci].merge_target = tid
                                written_zk.append(zk_candidates[ci])

        status = "cancelled" if plan.get("status") == "cancelled" else "complete"
        if plan.get("status") == "cancelled":
            from ctw_types import WorkflowDeviation
            plan.setdefault("deviations", []).append(WorkflowDeviation(
                axis="cancellation",
                original_value="in_progress",
                new_value="cancelled",
                reason="Human cancelled during execution",
            ))

        written_files = ingest_result.written_files if ingest_result else []

        _ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        result = {
            "run_id": run_id,
            "timestamp": _ts,
            "url": getattr(source, "url", "") if source else "",
            "status": status,
            "content_type": plan.get("content_type", ""),
            "confidence": plan.get("confidence", 0.0),
            "recommended_depth": plan.get("recommended_depth", ""),
            "deviations": plan.get("deviations", []),
            "source": source,
            "classify": classify_result,
            "level": level_result,
            "ingest": ingest_result,
            "zk_candidates": zk_candidates,
            "written_zk": written_zk,
            "written_files": written_files,
            "files_written": len(written_files),
            "errors": errors,
        }

        # Record in-memory state
        self._current_run = {"run_id": run_id, "status": status,
                             "type": plan.get("content_type_name", "unknown"),
                             "date": time.strftime("%Y-%m-%d"),
                             "errors": errors,
                             "files_written": len(written_files)}
        self._runs.append(self._current_run)

        # Persist to disk
        try:
            self._store.save_run(result)
        except Exception:
            pass  # persistence failure is non-fatal

        return result

    # ---- Status and history (in-memory for MVP) ----

    def status(self) -> dict:
        """Return current processing stage and progress."""
        return {
            "stage": self._current_run.get("status", "idle"),
            "run_id": self._current_run.get("run_id", ""),
            "messages": [self._current_run.get("status", "idle")],
            "decisions": [],
        }

    def history(self) -> list[dict]:
        """Return list of past Processing Runs."""
        return self._runs

    # ---- Existing analyze() preserved ----

    def analyze(self, prompt: str, auto_run: bool = True, auto_write: bool = False) -> AnalysisResult:
        """
        智能分析入口。

        Args:
            prompt: 人类输入文本（可含 URL + 描述）
            auto_run: True=自动推进管线, False=只做分类
            auto_write: True=将 ingest 产出写入磁盘, False=只生成不写盘

        Returns:
            AnalysisResult 含进度、结果、建议
        """
        t0 = time.time()
        result = AnalysisResult()
        result.progress = AnalysisProgress(stage="parsing")

        # ── Phase 1: 解析 ──
        urls, intent, _ = analyze_prompt(prompt)
        result.progress.total_sources = len(urls)
        result.progress.messages.append(f"🔍 解析到 {len(urls)} 个链接")

        if not urls and not intent.strip():
            result.summary = "未检测到可分析的资料。请提供至少一个 URL 或更详细的描述。"
            result.action_required = True
            result.total_time_ms = (time.time() - t0) * 1000
            return result

        # 无 URL 但有意图文本
        if not urls:
            result.progress.messages.append("⚠️ 未检测到 URL，请提供资料链接以便分析")
            result.summary = f"从描述中提取到意图：「{intent[:100]}」，但缺少资料链接。请补充 URL。"
            result.action_required = True
            result.total_time_ms = (time.time() - t0) * 1000
            return result

        # ── Phase 2: 为每个 URL 创建 source ──
        for i, url in enumerate(urls):
            source = AnalyzedSource(
                url=url,
                title=extract_title_from_prompt(intent, urls) if i == 0 else "",
                description=intent if len(urls) == 1 else "",
                source_type=infer_source_type(url),
            )
            source.quality_score = assess_source_quality(source)
            source.missing_fields = identify_missing_fields(source)
            source.needs_more_info = source.quality_score < 0.5
            result.sources.append(source)

        result.progress.stage = "classifying"
        result.progress.messages.append(f"📊 正在为 {len(result.sources)} 个资料分类...")

        # ── Phase 3: 分类 + 质量检查 ──
        for i, source in enumerate(result.sources):
            result.progress.current_source = source.url
            result.progress.processed = i

            # 3a. 如果需要更多信息，先返回追问
            if source.needs_more_info and not auto_run:
                result.followup_questions.extend([
                    f"📎 [{source.url}]: 请提供以下信息 → {', '.join(source.missing_fields)}"
                ])
                result.action_required = True
                continue

            # 3b. 执行分类
            try:
                # Fetch content if source is empty (video/remote URLs)
                if not source.content and not source.description:
                    fetcher = self._get_fetcher()
                    if fetcher:
                        try:
                            fetched = fetcher.fetch(source.url)
                            if fetched.title:
                                source.title = fetched.title
                            if fetched.description:
                                source.description = fetched.description
                            if fetched.content:
                                source.content = fetched.content
                            source.quality_score = assess_source_quality(source)
                            source.missing_fields = identify_missing_fields(source)
                            source.needs_more_info = source.quality_score < 0.5
                        except Exception:
                            pass

                si = SourceInput(
                    url=source.url,
                    title=source.title or source.url.rsplit('/', 1)[-1],
                    description=source.description,
                    content=source.content,
                    source_type=source.source_type,
                )
                source.classify = self.classifier.classify(si)
                result.progress.messages.append(
                    f"  ✓ [{source.url[-40:]}] → {source.classify.content_type_name} "
                    f"(置信度 {source.classify.confidence:.0%})"
                )
            except Exception as e:
                source.errors.append(f"分类失败: {e}")
                result.progress.messages.append(f"  ✗ [{source.url[-40:]}] → 分类失败: {e}")
                continue

            # 3c. 自动决定深度
            auto_depth, reason = auto_decide_depth(source.classify, source.quality_score)
            source.auto_depth = auto_depth
            result.progress.decisions.append(f"[{source.url[-40:]}] {reason}")

            # 3d. 路由深度
            try:
                source.level = self.router.route(source.classify)
                # 如果自动深度低于路由默认，使用自动深度
                level_values = {
                    InfoLevel.L0: 0, InfoLevel.L1: 1,
                    InfoLevel.L2: 2, InfoLevel.L3: 3, InfoLevel.L4: 4
                }
                if level_values.get(auto_depth, 0) < level_values.get(source.level.level, 1):
                    # 自动决策降级
                    source.level.level = auto_depth
                    source.level.reason = f"自动降级 — {reason}"
            except Exception as e:
                source.errors.append(f"路由失败: {e}")

        result.progress.processed = len(result.sources)
        result.progress.stage = "routing"

        # ── Phase 4: 判断是否需要人类介入 ──
        low_quality_sources = [s for s in result.sources if s.needs_more_info]
        if low_quality_sources and not auto_run:
            result.action_required = True
            result.followup_questions = [
                f"📎 [{s.url}]: 缺少 {', '.join(s.missing_fields)}，是否继续以基本信息处理？"
                for s in low_quality_sources
            ]
            result.summary = (
                f"已分类 {len(result.sources)} 个资料，{len(low_quality_sources)} 个信息不完整。"
            )
            result.total_time_ms = (time.time() - t0) * 1000
            return result

        # ── Phase 5: 执行摄入 ──
        if auto_run:
            result.progress.stage = "ingesting"
            result.progress.messages.append(f"📝 正在摄入 {len(result.sources)} 个资料...")

            for i, source in enumerate(result.sources):
                if source.errors:
                    continue
                try:
                    si = SourceInput(
                        url=source.url,
                        title=source.title or source.url.rsplit('/', 1)[-1],
                        description=source.description,
                        content=source.content,
                        source_type=source.source_type,
                    )
                    ingest_result = self.ingest.ingest(si, source.classify, source.level,
                                                       auto_write=auto_write)
                    source.ingest = ingest_result
                    written_info = ""
                    if auto_write and ingest_result.written_files:
                        written_info = f", {len(ingest_result.written_files)} 个已写盘"
                    result.progress.messages.append(
                        f"  ✓ [{source.url[-40:]}] → {len(ingest_result.output_files)} 个产出文件, "
                        f"{len(ingest_result.zk_candidates)} 个 ZK 候选{written_info}"
                    )
                except Exception as e:
                    source.errors.append(f"摄入失败: {e}")
                    result.progress.messages.append(f"  ✗ [{source.url[-40:]}] → 摄入失败: {e}")

        result.progress.stage = "done"

        # ── Phase 6: 生成摘要和建议 ──
        result.summary = self._build_summary(result)
        result.recommendations = self._build_recommendations(result)
        result.followup_questions = self._build_followups(result)
        result.action_required = bool(result.followup_questions)

        result.total_time_ms = (time.time() - t0) * 1000
        return result

    def _build_summary(self, result: AnalysisResult) -> str:
        """构建分析摘要"""
        lines = [f"## CTW 分析完成 — {len(result.sources)} 个资料"]
        type_counts = {}
        for s in result.sources:
            if s.classify:
                ct = s.classify.content_type_name
                type_counts[ct] = type_counts.get(ct, 0) + 1

        if type_counts:
            type_summary = ', '.join(f"{v}x {k}" for k, v in type_counts.items())
            lines.append(f"类型分布: {type_summary}")

        total_outputs = sum(
            len(s.ingest.output_files) for s in result.sources if s.ingest
        )
        total_zk = sum(
            len(s.ingest.zk_candidates) for s in result.sources if s.ingest
        )
        lines.append(f"产出: {total_outputs} 个文件, {total_zk} 个 ZK 候选")

        errors = [s for s in result.sources if s.errors]
        if errors:
            lines.append(f"⚠️ {len(errors)} 个资料处理出错")

        return '\n'.join(lines)

    def _build_recommendations(self, result: AnalysisResult) -> list[str]:
        """构建行动建议"""
        recs = []
        for s in result.sources:
            if s.classify:
                ct = s.classify.content_type
                level = s.auto_depth

                if ct == ContentType.SECURITY_RESEARCH:
                    recs.append(f"🔴 [{s.url[-40:]}] 安全研究 — 建议立即处理")
                elif ct == ContentType.TECH_NEWS:
                    recs.append(f"📰 [{s.url[-40:]}] 技术新闻 — 速览后归档")
                elif level in (InfoLevel.L3, InfoLevel.L4):
                    recs.append(f"📚 [{s.url[-40:]}] {s.classify.content_type_name} L{level.value[-1]} — 建议深度阅读")
                elif s.needs_more_info:
                    recs.append(f"❓ [{s.url[-40:]}] 信息不足 — 建议补充标题/内容后重新分析")
                else:
                    recs.append(f"📋 [{s.url[-40:]}] {s.classify.content_type_name} L{level.value[-1]} — 已自动处理")

        if not recs:
            recs.append("暂无特殊建议")
        return recs

    def _build_followups(self, result: AnalysisResult) -> list[str]:
        """构建追问列表"""
        followups = []
        for s in result.sources:
            if s.needs_more_info and s.quality_score < 0.3:
                followups.append(
                    f"📎 [{s.url}]: 缺少标题和内容，请提供更多信息以便深入分析"
                )
        return followups

    def get_status(self, result: AnalysisResult) -> dict:
        """获取分析状态（供心跳/轮询使用）"""
        return {
            "stage": result.progress.stage,
            "total": result.progress.total_sources,
            "processed": result.progress.processed,
            "messages": result.progress.messages[-5:],  # 最近5条
            "decisions": result.progress.decisions,
            "action_required": result.action_required,
            "followup_questions": result.followup_questions,
            "total_time_ms": result.total_time_ms,
        }

    def continue_analysis(
        self, result: AnalysisResult, supplements: dict[str, dict]
    ) -> AnalysisResult:
        """
        人类补充信息后继续分析。

        Args:
            result: 之前返回的 AnalysisResult
            supplements: {url: {"title": "...", "content": "...", ...}}

        Returns:
            更新后的 AnalysisResult
        """
        t0 = time.time()
        result.progress.stage = "classifying"
        result.progress.messages.append("📥 收到补充信息，重新分析...")

        for source in result.sources:
            if source.url in supplements:
                extra = supplements[source.url]
                if 'title' in extra:
                    source.title = extra['title']
                if 'content' in extra:
                    source.content = extra['content']
                if 'description' in extra:
                    source.description = extra['description']
                # 重新评估
                source.quality_score = assess_source_quality(source)
                source.missing_fields = identify_missing_fields(source)
                source.needs_more_info = source.quality_score < 0.5

        # 重新分类和摄入
        for source in result.sources:
            if source.needs_more_info:
                continue
            try:
                si = SourceInput(
                    url=source.url,
                    title=source.title or source.url.rsplit('/', 1)[-1],
                    description=source.description,
                    content=source.content,
                    source_type=source.source_type,
                )
                source.classify = self.classifier.classify(si)
                auto_depth, reason = auto_decide_depth(source.classify, source.quality_score)
                source.auto_depth = auto_depth
                source.level = self.router.route(source.classify)
                ingest_result = self.ingest.ingest(si, source.classify, source.level)
                source.ingest = ingest_result
            except Exception as e:
                source.errors.append(str(e))

        result.progress.stage = "done"
        result.summary = self._build_summary(result)
        result.recommendations = self._build_recommendations(result)
        result.followup_questions = self._build_followups(result)
        result.action_required = bool(result.followup_questions)
        result.total_time_ms = (time.time() - t0) * 1000
        return result


# ============================================================
# Interaction helpers
# ============================================================

def _safe_emoji(text: str) -> str:
    """Replace emoji with ASCII equivalents for Windows console compatibility."""
    replacements = [
        ('\U0001f50d', '[search]'),
        ('\u26a0\ufe0f', '[!]'), ('\u26a0', '[!]'),
        ('\U0001f4ca', '[chart]'), ('\U0001f4dd', '[write]'),
        ('\U0001f4ce', '[+]'), ('\U0001f4cb', '[*]'),
        ('\U0001f4da', '[book]'), ('\U0001f4f0', '[news]'),
        ('\U0001f534', '[!!]'), ('\u2753', '[?]'),
        ('\U0001f9e0', '[auto]'), ('\U0001f4c4', '[doc]'),
        ('\u2713', 'V'), ('\u2717', 'X'),
        ('\u23f1\ufe0f', '[time]'), ('\u23f1', '[time]'),
        ('\U0001f4e5', '[inbox]'),
    ]
    for emoji, replacement in replacements:
        text = text.replace(emoji, replacement)
    return text


def format_analysis_for_user(result: AnalysisResult) -> str:
    """将分析结果格式化为人类可读的文本"""
    lines = []
    lines.append(result.summary)
    lines.append("")

    # 进度
    for msg in result.progress.messages:
        lines.append(f"  {msg}")

    # 决策
    for dec in result.progress.decisions:
        lines.append(f"  🧠 {dec}")

    # 建议
    if result.recommendations:
        lines.append("")
        lines.append("### 📋 建议行动")
        for rec in result.recommendations:
            lines.append(f"  {rec}")

    # 追问
    if result.followup_questions:
        lines.append("")
        lines.append("### ❓ 需要补充信息")
        for q in result.followup_questions:
            lines.append(f"  {q}")

    # 每个资料的详细信息
    for s in result.sources:
        if s.classify:
            lines.append("")
            lines.append(f"---")
            lines.append(f"### 📄 {s.title or s.url[-50:]}")
            lines.append(f"- 类型: {s.classify.content_type_name} (置信度 {s.classify.confidence:.0%})")
            lines.append(f"- 深度: {s.auto_depth.value} ({s.level.level_name if s.level else 'N/A'})")
            if s.ingest:
                lines.append(f"- 产出: {len(s.ingest.output_files)} 文件")
                for f in s.ingest.output_files[:3]:
                    lines.append(f"  - {f}")
                if len(s.ingest.output_files) > 3:
                    lines.append(f"  - ...共 {len(s.ingest.output_files)} 个文件")
            if s.errors:
                lines.append(f"- ⚠️ 错误: {'; '.join(s.errors)}")

    lines.append("")
    lines.append(f"[time] 总耗时: {result.total_time_ms:.0f}ms")
    return _safe_emoji('\n'.join(lines))


# ============================================================
# Convenience functions
# ============================================================

_analyzer: Optional[CTWAnalyzer] = None


def get_analyzer() -> CTWAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = CTWAnalyzer()
    return _analyzer


def ctw_ana(prompt: str, auto_run: bool = True, auto_write: bool = False) -> AnalysisResult:
    """快捷入口: 等同于 /ctw_ana"""
    return get_analyzer().analyze(prompt, auto_run=auto_run, auto_write=auto_write)
