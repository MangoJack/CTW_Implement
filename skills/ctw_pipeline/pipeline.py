"""CTW Pipeline — 主控管线编排器

将 ctw_classify → ctw_infolevel → ctw_ingest 串联为一个完整的处理管线。
"""
import sys
import os
from typing import Optional

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "lib"))

from ctw_config import CTWConfig

sys.path.insert(0, os.path.join(_ROOT, "skills", "ctw_classify"))
from classifier import TaxonomyClassifier

sys.path.insert(0, os.path.join(_ROOT, "skills", "ctw_infolevel"))
from router import InfoLevelRouter

sys.path.insert(0, os.path.join(_ROOT, "skills", "ctw_ingest"))
from ingest import LLMWikiIngest


class CTWPipeline:
    """CTW 完整管线：分类 → 深度路由 → 摄入 → 产出

    使用示例:

        pipeline = CTWPipeline()
        result = pipeline.run(source_input)

    Gates 在管线的关键节点被触发：
        CLASSIFY → APPROVE_OUTPUT → APPROVE_ZK → PROMOTE
    """

    def __init__(self, project_path: Optional[str] = None):
        self.config = CTWConfig(ctw_project_path=project_path)
        self.classifier = TaxonomyClassifier()
        self.router = InfoLevelRouter()
        self.ingest = LLMWikiIngest()

    def run(
        self,
        source: "SourceInput",                        # noqa: F821
        classify_override: Optional["ClassifyResult"] = None,  # noqa: F821
        level_override: Optional["LevelResult"] = None,       # noqa: F821
        auto_write: bool = False,                     # 自动写盘
        auto_approve: bool = False,                   # 跳过人类审批
    ) -> "PipelineResult":                                  # noqa: F821
        """执行完整管线。

        Args:
            source: 信息源输入
            classify_override: 可选，跳过分类直接指定结果
            level_override: 可选，跳过深度路由直接指定结果
            auto_write: True → 将 ingest 产出写入磁盘
            auto_approve: True → 跳过人类审批 Gate，直接标记 PASSED

        Returns:
            PipelineResult 包含完整的管线产出
        """
        from ctw_types import PipelineResult, GateTrigger, GateName, GateStatus

        result = PipelineResult(source=source)
        result.status = "processing"

        # === Stage 1: CLASSIFY ===
        if classify_override:
            result.classify = classify_override
        else:
            result.classify = self.classifier.classify(source)

        result.gates_triggered.append(GateTrigger(
            gate=GateName.CLASSIFY,
            stage="classify",
            condition=f"type={result.classify.content_type.value}",
            data={"content_type": result.classify.content_type.value,
                   "confidence": result.classify.confidence},
            status=GateStatus.PASSED,
        ))

        # === Stage 2: ROUTE to InfoLevel ===
        if level_override:
            result.level = level_override
        else:
            result.level = self.router.route(result.classify)

        # === Stage 3: INGEST to LLM Wiki (with optional auto-write) ===
        result.ingest = self.ingest.ingest(source, result.classify, result.level,
                                           auto_write=auto_write)

        # Gate: APPROVE_OUTPUT
        output_gate_status = GateStatus.PASSED if auto_approve else GateStatus.PENDING_MODIFIED
        result.gates_triggered.append(GateTrigger(
            gate=GateName.APPROVE_OUTPUT,
            stage="ingest",
            condition=f"output_files={len(result.ingest.output_files)}",
            data={"output_count": len(result.ingest.output_files),
                   "zk_count": len(result.ingest.zk_candidates),
                   "written_count": len(result.ingest.written_files),
                   "written": result.ingest.written_files},
            status=output_gate_status,
        ))

        # === Stage 4: ZK candidates ===
        from ctw_types import ZkCandidate
        for zk_title in result.ingest.zk_candidates:
            result.zk_notes.append(ZkCandidate(
                id="",
                title=zk_title,
                abstract=zk_title,
                confidence=0.7,
            ))

        if result.zk_notes:
            zk_gate_status = GateStatus.PASSED if auto_approve else GateStatus.PENDING_MODIFIED
            result.gates_triggered.append(GateTrigger(
                gate=GateName.APPROVE_ZK,
                stage="zk",
                condition=f"candidates={len(result.zk_notes)}",
                data={"candidate_count": len(result.zk_notes)},
                status=zk_gate_status,
            ))

        # === Collect all output files ===
        result.output_files = result.ingest.output_files.copy()
        result.written_files = result.ingest.written_files.copy()

        # Determine final status
        if result.ingest.human_feedback_required and not auto_approve:
            result.status = "waiting_human"
        elif auto_approve:
            result.status = "complete"
        else:
            result.status = "complete"

        return result

    def status(self) -> dict:
        """获取管线状态摘要。"""
        return {
            "classifier": type(self.classifier).__name__,
            "router": type(self.router).__name__,
            "ingest": type(self.ingest).__name__,
            "config": self.config.project_path or "default",
        }


# Convenience function
def run_pipeline(source_data: dict) -> "PipelineResult":  # noqa: F821
    """从字典快速执行管线。

    Args:
        source_data: {"url": ..., "title": ..., "content": ..., ...}

    Returns:
        PipelineResult
    """
    from ctw_types import SourceInput

    pipeline = CTWPipeline()
    source = SourceInput(**{k: v for k, v in source_data.items()
                            if k in SourceInput.__dataclass_fields__})
    return pipeline.run(source)
