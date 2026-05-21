"""CTW 运行时状态持久化 — JSONL 追加写入，按月分文件"""
import json
import os
import time
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Optional


def _make_serializable(obj):
    """递归转换 dataclass / Path / 枚举 为可 JSON 序列化的 dict/str"""
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_serializable(v) for v in obj]
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "value"):
        return obj.value
    if is_dataclass(obj):
        result = {}
        for f in fields(obj):
            v = getattr(obj, f.name)
            result[f.name] = _make_serializable(v)
        return result
    return obj


class RunStore:
    """JSONL 持久化存储，每次 pipeline run 追加一行。

    目录结构:
        state/runs/
        ├── 2026-05.jsonl
        ├── 2026-06.jsonl
        └── index.json       ← run_id → (file, byte_offset) 快速索引

    Usage:
        store = RunStore()
        store.save_run(result_dict)
        runs = store.load_runs(since="2026-05-01")
        devs = store.load_deviations()
    """

    def __init__(self, state_dir: str = None):
        if state_dir:
            self._state_dir = Path(state_dir)
        else:
            impl = os.environ.get("CTW_IMPLEMENT_PATH")
            if impl:
                base = Path(impl)
            else:
                base = Path(__file__).resolve().parent.parent
            self._state_dir = base / "state"
        self._runs_dir = self._state_dir / "runs"
        self._index_path = self._state_dir / "index.json"
        self._index: dict[str, dict] = {}
        self._index_loaded = False

    # ── public API ──

    def save_run(self, run_result: dict) -> str:
        """持久化一次 run 的完整结果，追加一行 JSONL。

        Returns:
            run_id
        """
        self._runs_dir.mkdir(parents=True, exist_ok=True)
        run_id = run_result.get("run_id") or time.strftime("%Y%m%d%H%M%S")
        run_result["run_id"] = run_id

        flat = _make_serializable(run_result)
        line = json.dumps(flat, ensure_ascii=False, separators=(",", ":"))

        month = run_id[:6]  # YYYYMM
        file_path = self._runs_dir / f"{month}.jsonl"

        with open(file_path, "a", encoding="utf-8") as f:
            byte_offset = f.tell()
            f.write(line + "\n")

        self._ensure_index_loaded()
        self._index[run_id] = {"file": str(file_path), "offset": byte_offset}
        self._save_index()

        return run_id

    def load_runs(self, since: str = None, limit: int = None) -> list[dict]:
        """加载全部 run 记录，按时间倒序。

        Args:
            since: "2026-05-01" 或 "20260501" 格式
            limit: 最大返回条数
        """
        results = []
        if since:
            since_month = since.replace("-", "")[:6]
        else:
            since_month = None

        for jsonl_file in sorted(self._runs_dir.glob("*.jsonl"), reverse=True):
            if since_month and jsonl_file.stem < since_month:
                continue
            try:
                with open(jsonl_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        run = json.loads(line)
                        if since:
                            ts = run.get("timestamp") or run.get("run_id", "")
                            ts_compact = ts.replace("-", "")[:8]
                            if ts_compact < since.replace("-", ""):
                                continue
                        results.append(run)
                        if limit and len(results) >= limit:
                            results.sort(key=lambda r: r.get("run_id", ""), reverse=True)
                            return results
            except (json.JSONDecodeError, OSError):
                continue

        results.sort(key=lambda r: r.get("run_id", ""), reverse=True)
        if limit:
            results = results[:limit]
        return results

    def load_deviations(self, since: str = None) -> list[dict]:
        """只加载含有 deviation 的 run 记录。

        Returns:
            list of runs (each containing non-empty 'deviations' key)
        """
        all_runs = self.load_runs(since=since)
        return [r for r in all_runs if r.get("deviations") and len(r["deviations"]) > 0]

    def get_run(self, run_id: str) -> Optional[dict]:
        """按 run_id 查找单条记录。"""
        self._ensure_index_loaded()
        entry = self._index.get(run_id)
        if not entry:
            return self._scan_for_run(run_id)
        try:
            with open(entry["file"], "r", encoding="utf-8") as f:
                f.seek(entry["offset"])
                line = f.readline()
                return json.loads(line)
        except (OSError, json.JSONDecodeError):
            return self._scan_for_run(run_id)

    # ── index ──

    def _ensure_index_loaded(self):
        if self._index_loaded:
            return
        try:
            with open(self._index_path, "r", encoding="utf-8") as f:
                self._index = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._index = {}
        self._index_loaded = True

    def _save_index(self):
        self._state_dir.mkdir(parents=True, exist_ok=True)
        with open(self._index_path, "w", encoding="utf-8") as f:
            json.dump(self._index, f, ensure_ascii=False, indent=2)

    def _scan_for_run(self, run_id: str) -> Optional[dict]:
        for jsonl_file in sorted(self._runs_dir.glob("*.jsonl"), reverse=True):
            try:
                with open(jsonl_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        if run_id in line:
                            return json.loads(line.strip())
            except (json.JSONDecodeError, OSError):
                continue
        return None
