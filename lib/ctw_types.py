# CTW Implement — 共享类型定义
"""
CTW Pipeline 中使用的所有类型定义和数据结构。
与 contextToWhatend/taxonomy/types.yaml 保持同步。
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ContentType(Enum):
    """内容类型 — 与 taxonomy/types.yaml 的 10 种类型一一对应"""
    TOOL_EXTENSION = "tool-extension"
    TOOL_REVIEW = "tool-review"
    PRACTICE_TUTORIAL = "practice-tutorial"
    ARCHITECTURE_ANALYSIS = "architecture-analysis"
    PAPER_REVIEW = "paper-review"
    TECH_NEWS = "tech-news"
    EXPERIENCE_SHARE = "experience-share"
    SPEC_STANDARD = "spec-standard"
    SECURITY_RESEARCH = "security-research"
    AI_AGENT = "ai-agent"
    UNKNOWN = "unknown"


class InfoLevel(Enum):
    """处理深度级别 — 与 infolevel/LEVELS.md 同步"""
    L0 = "L0"  # Quick Scan — 速览
    L1 = "L1"  # Tool Review — 工具评测
    L2 = "L2"  # Practice Deep-Dive — 实践深挖
    L3 = "L3"  # System Analysis — 系统分析
    L4 = "L4"  # Research Synthesis — 研究合成


class GateStatus(Enum):
    """Gate 状态"""
    PASSED = "passed"
    PENDING = "pending"
    PENDING_MODIFIED = "pending_modified"
    REJECTED = "rejected"
    SKIPPED = "skipped"
    DEFERRED = "defer"


class GateName(Enum):
    """Gate 名称 — 与 workflows/gates.yaml v2.0 同步"""
    CLASSIFY = "CLASSIFY"
    APPROVE_OUTPUT = "APPROVE_OUTPUT"
    APPROVE_ZK = "APPROVE_ZK"
    RESOLVE_CONFLICT = "RESOLVE_CONFLICT"
    PROMOTE = "PROMOTE"
    CONFIG_CHANGE = "CONFIG_CHANGE"


class SourceCategory(Enum):
    """LLM Wiki raw/ 子目录"""
    ARTICLES = "articles"
    PAPERS = "papers"
    CODE = "code"
    URLS = "urls"
    TRANSCRIPTS = "transcripts"


@dataclass
class ValueQuestion:
    """价值问题定义"""
    id: str
    question: str
    category: str
    priority: str  # critical / high / medium
    output_format: str
    skip_condition: Optional[str] = None


@dataclass
class SourceInput:
    """信息源输入"""
    url: str = ""
    title: str = ""
    description: str = ""
    content: str = ""  # 实际内容或摘要
    source_type: str = ""  # video / article / repo / pdf / url / chat
    raw_file_path: str = ""  # 在 raw/ 下的路径


@dataclass
class ClassifyResult:
    """类型分类结果"""
    content_type: ContentType = ContentType.UNKNOWN
    content_type_name: str = ""
    confidence: float = 0.0
    reason: str = ""
    suggested_level: InfoLevel = InfoLevel.L1
    value_questions: list[ValueQuestion] = field(default_factory=list)
    output_targets: dict = field(default_factory=dict)


@dataclass
class LevelResult:
    """深度路由结果"""
    level: InfoLevel = InfoLevel.L0
    level_name: str = ""
    confidence: float = 0.0
    reason: str = ""
    template: str = ""  # 对应模板路径
    processing_steps: list[str] = field(default_factory=list)


@dataclass
class GateTrigger:
    """Gate 触发事件"""
    gate: GateName
    stage: str
    condition: str
    data: dict = field(default_factory=dict)
    status: GateStatus = GateStatus.PENDING
    human_action: Optional[str] = None


@dataclass
class IngestResult:
    """LLM Wiki Ingest 结果"""
    source_summary: str = ""        # 源摘要页内容
    entity_pages: list[str] = field(default_factory=list)
    concept_pages: list[str] = field(default_factory=list)
    comparison_pages: list[str] = field(default_factory=list)
    zk_candidates: list[str] = field(default_factory=list)
    output_files: list[str] = field(default_factory=list)   # 计划写入的路径
    written_files: list[str] = field(default_factory=list)  # 实际已写入的路径
    human_feedback_required: bool = False


@dataclass
class ZkCandidate:
    """ZK 永久笔记候选"""
    id: str
    title: str
    abstract: str
    confidence: float = 0.0
    priority: int = 3  # 1-5, 1=最高
    links: list[str] = field(default_factory=list)
    merge_target: Optional[str] = None  # 如果需要合并到已有笔记
    status: str = "pending"


@dataclass
class PipelineResult:
    """完整 Pipeline 执行结果"""
    source: SourceInput
    classify: Optional[ClassifyResult] = None
    level: Optional[LevelResult] = None
    ingest: Optional[IngestResult] = None
    zk_notes: list[ZkCandidate] = field(default_factory=list)
    gates_triggered: list[GateTrigger] = field(default_factory=list)
    output_files: list[str] = field(default_factory=list)   # 计划产出的路径
    written_files: list[str] = field(default_factory=list)  # 实际已写入的路径
    errors: list[str] = field(default_factory=list)
    status: str = "init"  # init / processing / waiting_human / complete / error
