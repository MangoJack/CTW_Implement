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

# Bootstrap paths
_CTW_ROOT = r"D:\MainWorkSpace\CTW_Implement"
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

from ctw_types import (
    SourceInput, ClassifyResult, ContentType, InfoLevel,
    LevelResult, PipelineResult, GateTrigger, GateStatus, GateName,
    IngestResult, ZkCandidate, ValueQuestion,
)
from classifier import TaxonomyClassifier
from router import InfoLevelRouter
from ingest import LLMWikiIngest

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
