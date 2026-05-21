"""Tests for ctw_state (persistence) and patterns (analysis)."""
import json
import sys
import os
import tempfile
from pathlib import Path

import pytest

_CTW_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_CTW_ROOT, "lib"))
sys.path.insert(0, os.path.join(_CTW_ROOT, "skills", "ctw_analyzer"))

from ctw_state import RunStore, _make_serializable
from ctw_types import ContentType, InfoLevel, WorkflowDeviation
from patterns import PatternAnalyzer


# ═══════════════════════════════════════════
# Serialization
# ═══════════════════════════════════════════

class TestMakeSerializable:
    def test_enum_to_value(self):
        assert _make_serializable(ContentType.TOOL_EXTENSION) == "tool-extension"
        assert _make_serializable(InfoLevel.L3) == "L3"

    def test_path_to_str(self):
        assert _make_serializable(Path("/tmp/foo")) == str(Path("/tmp/foo"))

    def test_nested_dataclass(self):
        d = WorkflowDeviation(axis="type", original_value="a", new_value="b")
        flat = _make_serializable(d)
        assert flat["axis"] == "type"
        assert flat["original_value"] == "a"
        assert "timestamp" in flat

    def test_mixed_dict(self):
        d = {"type": ContentType.PAPER_REVIEW, "depth": InfoLevel.L4,
             "path": Path("/out")}
        flat = _make_serializable(d)
        assert flat == {"type": "paper-review", "depth": "L4",
                        "path": str(Path("/out"))}

    def test_list_of_enums(self):
        lst = [ContentType.TOOL_EXTENSION, ContentType.AI_AGENT]
        assert _make_serializable(lst) == ["tool-extension", "ai-agent"]


# ═══════════════════════════════════════════
# RunStore persistence
# ═══════════════════════════════════════════

class TestRunStore:
    @pytest.fixture
    def store(self):
        with tempfile.TemporaryDirectory() as td:
            yield RunStore(td)

    def test_save_and_load_single(self, store):
        store.save_run({"run_id": "20260521080000", "status": "complete"})
        runs = store.load_runs()
        assert len(runs) == 1
        assert runs[0]["run_id"] == "20260521080000"

    def test_save_generates_run_id(self, store):
        rid = store.save_run({"status": "init"})
        assert rid
        assert len(rid) == 14  # YYYYMMDDHHmmss

    def test_multiple_runs_returned_reverse_chronological(self, store):
        store.save_run({"run_id": "20260520080000", "status": "complete"})
        store.save_run({"run_id": "20260521080000", "status": "complete"})
        runs = store.load_runs()
        assert runs[0]["run_id"] > runs[1]["run_id"]

    def test_load_runs_with_since_filter(self, store):
        store.save_run({"run_id": "20260501080000", "status": "complete"})
        store.save_run({"run_id": "20260520080000", "status": "complete"})
        store.save_run({"run_id": "20260521080000", "status": "complete"})
        runs = store.load_runs(since="2026-05-20")
        assert len(runs) == 2

    def test_load_runs_with_since_compact_format(self, store):
        store.save_run({"run_id": "20260501080000"})
        store.save_run({"run_id": "20260521080000"})
        runs = store.load_runs(since="20260520")
        assert len(runs) == 1

    def test_load_runs_with_limit(self, store):
        for i in range(5):
            store.save_run({"run_id": f"2026052108000{i}"})
        assert len(store.load_runs(limit=2)) == 2

    def test_empty_store_returns_empty_list(self, store):
        assert store.load_runs() == []

    def test_jsonl_is_valid_json_per_line(self, store):
        store.save_run({"run_id": "20260521080000", "msg": "hello world"})
        store.save_run({"run_id": "20260521080001", "msg": "line 2"})
        runs_dir = store._runs_dir
        jsonl = list(runs_dir.glob("*.jsonl"))[0]
        with open(jsonl, "r", encoding="utf-8") as f:
            for line in f:
                json.loads(line)  # each line must be valid JSON

    def test_unicode_preserved(self, store):
        store.save_run({"run_id": "20260521080000", "title": "中文标题测试"})
        runs = store.load_runs()
        assert runs[0]["title"] == "中文标题测试"

    def test_dataclass_objects_serialized(self, store):
        from ctw_types import SourceInput
        src = SourceInput(url="https://github.com/x", source_type="repo",
                          title="Test", description="Desc", content="Body")
        store.save_run({"run_id": "20260521080000", "source": src})
        runs = store.load_runs()
        assert runs[0]["source"]["url"] == "https://github.com/x"

    def test_load_deviations_filters_non_empty(self, store):
        store.save_run({"run_id": "20260521080000", "status": "complete",
                        "deviations": [{"axis": "type"}]})
        store.save_run({"run_id": "20260521080001", "status": "complete",
                        "deviations": []})
        store.save_run({"run_id": "20260521080002", "status": "complete",
                        "deviations": None})
        devs = store.load_deviations()
        assert len(devs) == 1

    def test_get_run_by_id(self, store):
        store.save_run({"run_id": "20260521080000", "m": "a"})
        store.save_run({"run_id": "20260521080001", "m": "b"})
        found = store.get_run("20260521080001")
        assert found is not None
        assert found["m"] == "b"

    def test_get_run_missing(self, store):
        assert store.get_run("nonexistent") is None

    def test_month_partitioning(self, store):
        store.save_run({"run_id": "20260415080000", "status": "april"})
        store.save_run({"run_id": "20260521080000", "status": "may"})
        jsonl_files = list(store._runs_dir.glob("*.jsonl"))
        assert len(jsonl_files) == 2
        months = {f.stem for f in jsonl_files}
        assert months == {"202604", "202605"}


# ═══════════════════════════════════════════
# PatternAnalyzer — type corrections
# ═══════════════════════════════════════════

def _mk_store(runs_data):
    """Helper: create a RunStore in a temp dir, pre-populated."""
    td = tempfile.mkdtemp()
    store = RunStore(td)
    for rd in runs_data:
        store.save_run(rd)
    return store


class TestTypeCorrections:
    def test_single_correction_counted(self):
        store = _mk_store([{
            "run_id": "20260521080000", "url": "https://github.com/a/b",
            "content_type": "ai-agent",
            "deviations": [
                {"axis": "type", "original_value": "tool-extension",
                 "new_value": "ai-agent"},
            ],
        }])
        pa = PatternAnalyzer(store)
        corr = pa.analyze_type_corrections()
        assert corr["github.com"]["tool-extension"]["ai-agent"] == 1

    def test_two_same_corrections_trigger_auto_apply(self):
        store = _mk_store([{
            "run_id": f"2026052{i}080000", "url": "https://github.com/x",
            "content_type": "ai-agent",
            "deviations": [
                {"axis": "type", "original_value": "tool-extension",
                 "new_value": "ai-agent"},
            ],
        } for i in range(2)])
        pa = PatternAnalyzer(store)
        s = pa.get_suggestions("https://github.com/new", "tool-extension", "L1")
        assert s["type_auto_apply"] is True
        assert s["type_suggestion"] == "ai-agent"
        assert s["type_confidence"] == 2

    def test_one_correction_suggests_but_no_auto_apply(self):
        store = _mk_store([{
            "run_id": "20260521080000", "url": "https://github.com/x",
            "content_type": "ai-agent",
            "deviations": [
                {"axis": "type", "original_value": "tool-extension",
                 "new_value": "ai-agent"},
            ],
        }])
        pa = PatternAnalyzer(store)
        s = pa.get_suggestions("https://github.com/new", "tool-extension", "L1")
        assert s["type_suggestion"] == "ai-agent"
        assert s["type_auto_apply"] is False
        assert s["type_confidence"] == 1

    def test_different_domain_no_suggestion(self):
        store = _mk_store([{
            "run_id": "20260521080000", "url": "https://github.com/x",
            "deviations": [
                {"axis": "type", "original_value": "a", "new_value": "b"},
            ],
        }])
        pa = PatternAnalyzer(store)
        s = pa.get_suggestions("https://arxiv.org/abs/1234", "paper-review", "L4")
        assert s["type_auto_apply"] is False
        assert s["type_suggestion"] is None


# ═══════════════════════════════════════════
# PatternAnalyzer — depth preferences
# ═══════════════════════════════════════════

class TestDepthPreferences:
    def test_depth_up_preference(self):
        store = _mk_store([{
            "run_id": f"2026052{i}080000", "content_type": "paper-review",
            "deviations": [
                {"axis": "depth", "original_value": "L2", "new_value": "L4"},
            ],
        } for i in range(2)])
        pa = PatternAnalyzer(store)
        s = pa.get_suggestions("https://arxiv.org/abs/1", "paper-review", "L2")
        assert s["depth_auto_apply"] is True
        assert s["depth_direction"] == "up"
        assert s["depth_suggestion"] == "L3"

    def test_depth_down_preference(self):
        store = _mk_store([{
            "run_id": f"2026052{i}080000", "content_type": "tech-news",
            "deviations": [
                {"axis": "depth", "original_value": "L2", "new_value": "L0"},
            ],
        } for i in range(2)])
        pa = PatternAnalyzer(store)
        s = pa.get_suggestions("https://example.com/n", "tech-news", "L2")
        assert s["depth_auto_apply"] is True
        assert s["depth_direction"] == "down"
        assert s["depth_suggestion"] == "L1"

    def test_one_depth_deviation_suggests_only(self):
        store = _mk_store([{
            "run_id": "20260521080000", "content_type": "ai-agent",
            "deviations": [
                {"axis": "depth", "original_value": "L1", "new_value": "L3"},
            ],
        }])
        pa = PatternAnalyzer(store)
        s = pa.get_suggestions("https://github.com/x", "ai-agent", "L1")
        assert s["depth_suggestion"] is not None
        assert s["depth_auto_apply"] is False

    def test_inconsistent_direction_no_auto_apply(self):
        store = _mk_store([
            {"run_id": "20260521080000", "content_type": "ai-agent",
             "deviations": [
                 {"axis": "depth", "original_value": "L1", "new_value": "L3"},
             ]},
            {"run_id": "20260521080001", "content_type": "ai-agent",
             "deviations": [
                 {"axis": "depth", "original_value": "L3", "new_value": "L1"},
             ]},
        ])
        pa = PatternAnalyzer(store)
        s = pa.get_suggestions("https://github.com/x", "ai-agent", "L1")
        # tied 1 up, 1 down → neither reaches threshold of 2
        assert s["depth_auto_apply"] is False


# ═══════════════════════════════════════════
# PatternAnalyzer — trend reports
# ═══════════════════════════════════════════

class TestTrendReports:
    def test_empty_report(self):
        store = _mk_store([])
        pa = PatternAnalyzer(store)
        r = pa.generate_trend_report(days=30)
        assert r["total_runs"] == 0

    def test_type_distribution(self):
        runs = []
        for i in range(2):
            runs.append({"run_id": f"2026052{i}080000", "content_type": "tool-extension",
                         "status": "complete", "confidence": 0.9,
                         "recommended_depth": "L1", "files_written": 3})
            runs.append({"run_id": f"2026052{i}090000", "content_type": "paper-review",
                         "status": "complete", "confidence": 0.85,
                         "recommended_depth": "L4", "files_written": 2})
        store = _mk_store(runs)
        pa = PatternAnalyzer(store)
        r = pa.generate_trend_report(days=30)
        assert r["total_runs"] == 4
        assert r["type_distribution"]["tool-extension"] == 2
        assert r["type_distribution"]["paper-review"] == 2
        assert r["complete"] == 4

    def test_cancellation_counted(self):
        store = _mk_store([
            {"run_id": "20260521080000", "status": "complete", "files_written": 1},
            {"run_id": "20260521080001", "status": "cancelled", "files_written": 0},
        ])
        pa = PatternAnalyzer(store)
        r = pa.generate_trend_report(days=30)
        assert r["complete"] == 1
        assert r["cancelled"] == 1
        assert r["deviations_total"] == 0

    def test_deviation_rate(self):
        store = _mk_store([
            {"run_id": "20260521080000", "status": "complete",
             "deviations": [{"axis": "depth"}]},
            {"run_id": "20260521080001", "status": "complete",
             "deviations": []},
        ])
        pa = PatternAnalyzer(store)
        r = pa.generate_trend_report(days=30)
        assert r["deviations_total"] == 1
        assert r["deviation_rate"] == 0.5

    def test_avg_confidence(self):
        store = _mk_store([
            {"run_id": "20260521080000", "confidence": 0.8},
            {"run_id": "20260521080001", "confidence": 0.9},
        ])
        pa = PatternAnalyzer(store)
        r = pa.generate_trend_report(days=30)
        assert r["avg_confidence"] == 0.85


# ═══════════════════════════════════════════
# Integration: learned deviations in plan
# ═══════════════════════════════════════════

class TestLearnedDeviationIntegration:
    def test_learned_type_deviation_has_source_field(self):
        """WorkflowDeviation must accept source='learned'."""
        d = WorkflowDeviation(
            axis="type",
            original_value="tool-extension",
            new_value="ai-agent",
            reason="learned: user corrects to ai-agent (2x)",
            source="learned",
        )
        assert d.source == "learned"
        assert d.axis == "type"
