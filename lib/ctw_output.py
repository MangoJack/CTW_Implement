# CTW Implement — 输出格式化器
"""
CTW Pipeline 结果的结构化输出。将处理结果格式化为人类可读的 Markdown。
"""
from ctw_types import (
    ClassifyResult, LevelResult, IngestResult, ZkCandidate,
    PipelineResult, GateTrigger, GateStatus
)


class OutputFormatter:
    """Pipeline 结果格式化器"""

    @staticmethod
    def format_classify_result(result: ClassifyResult) -> str:
        """格式化分类结果"""
        lines = [
            "## 📋 类型分类结果",
            "",
            f"| 字段 | 值 |",
            f"|------|-----|",
            f"| 类型 | **{result.content_type_name}** ({result.content_type.value}) |",
            f"| 置信度 | {result.confidence:.0%} |",
            f"| 建议深度 | {result.suggested_level.value} |",
            f"| 理由 | {result.reason} |",
            "",
            "### 🎯 需要回答的价值问题",
            "",
        ]
        if result.value_questions:
            for q in result.value_questions:
                priority_icon = "🔴" if q.priority == "critical" else "🟡" if q.priority == "high" else "🟢"
                skip_note = f" ⚠️ 可跳过: {q.skip_condition}" if q.skip_condition else ""
                lines.append(f"- {priority_icon} **{q.question}** `[{q.id}]`{skip_note}")
        return "\n".join(lines)

    @staticmethod
    def format_level_result(result: LevelResult) -> str:
        """格式化深度路由结果"""
        lines = [
            "## 🎚️ 深度路由结果",
            "",
            f"| 字段 | 值 |",
            f"|------|-----|",
            f"| 级别 | **{result.level_name}** ({result.level.value}) |",
            f"| 置信度 | {result.confidence:.0%} |",
            f"| 理由 | {result.reason} |",
            f"| 模板 | `{result.template}` |",
        ]
        if result.processing_steps:
            lines.append("")
            lines.append("### 处理步骤")
            for i, step in enumerate(result.processing_steps, 1):
                lines.append(f"{i}. {step}")
        return "\n".join(lines)

    @staticmethod
    def format_ingest_result(result: IngestResult) -> str:
        """格式化 Ingest 结果"""
        lines = [
            "## 📥 LLM Wiki Ingest 结果",
            "",
            f"| 产出 | 数量 |",
            f"|------|------|",
            f"| 源摘要页 | {1 if result.source_summary else 0} |",
            f"| 概念页 | {len(result.concept_pages)} |",
            f"| 实体页 | {len(result.entity_pages)} |",
            f"| 对比页 | {len(result.comparison_pages)} |",
            f"| ZK 候选 | {len(result.zk_candidates)} |",
        ]
        if result.zk_candidates:
            lines.append("")
            lines.append("### ZK 原子化候选清单")
            for c in result.zk_candidates:
                lines.append(f"- [ ] {c}")
        if result.human_feedback_required:
            lines.append("\n⚠️ **需要人类审阅**")
        return "\n".join(lines)

    @staticmethod
    def format_zk_candidates(candidates: list[ZkCandidate]) -> str:
        """格式化 ZK 候选清单"""
        lines = ["## 🧠 ZK 永久笔记候选", ""]
        for c in candidates:
            priority_bar = "█" * c.priority + "░" * (5 - c.priority)
            lines.append(f"### [{c.id}] {c.title}")
            lines.append(f"优先级: [{priority_bar}] ({c.priority}/5) | 置信度: {c.confidence:.0%}")
            lines.append(f"")
            lines.append(c.abstract)
            if c.links:
                lines.append(f"\n链接: {', '.join(c.links)}")
            if c.merge_target:
                lines.append(f"🔄 建议合并到: {c.merge_target}")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def format_gate(gate: GateTrigger) -> str:
        """格式化单个 Gate"""
        icon = "✅" if gate.status == GateStatus.PASSED else "⚠️" if gate.status in (GateStatus.PENDING, GateStatus.PENDING_MODIFIED) else "❌"
        return f"  {icon} **{gate.gate.value}** — {gate.stage} — {gate.status.value}"

    @staticmethod
    def format_pipeline_result(result: PipelineResult) -> str:
        """格式化完整 Pipeline 结果"""
        lines = [
            f"# CTW Pipeline 结果 — {result.source.title or '未命名'}",
            "",
            f"| 阶段 | 状态 |",
            f"|------|------|",
        ]
        if result.classify:
            lines.append(f"| 类型分类 | ✅ {result.classify.content_type_name} |")
        if result.level:
            lines.append(f"| 深度路由 | ✅ {result.level.level_name} |")
        if result.ingest:
            lines.append(f"| Ingest | {'✅' if not result.errors else '❌'} |")
        lines.append(f"| ZK 笔记 | {len(result.zk_notes)} 条 |")
        lines.append(f"| Gate 触发 | {len(result.gates_triggered)} 次 |")
        lines.append("")

        if result.classify:
            lines.append(OutputFormatter.format_classify_result(result.classify))
            lines.append("")
        if result.level:
            lines.append(OutputFormatter.format_level_result(result.level))
            lines.append("")
        if result.ingest:
            lines.append(OutputFormatter.format_ingest_result(result.ingest))
            lines.append("")
        if result.zk_notes:
            lines.append(OutputFormatter.format_zk_candidates(result.zk_notes))

        if result.gates_triggered:
            lines.append("## 🚪 Gate 状态")
            for gate in result.gates_triggered:
                lines.append(OutputFormatter.format_gate(gate))
            lines.append("")

        if result.output_files:
            lines.append("## 📂 产出文件")
            for f in result.output_files:
                lines.append(f"- {f}")
            lines.append("")

        if result.errors:
            lines.append("## ❌ 错误")
            for e in result.errors:
                lines.append(f"- {e}")

        lines.append(f"\n**最终状态**: {result.status}")
        return "\n".join(lines)
