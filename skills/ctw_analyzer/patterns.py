"""CTW 模式分析 — 从历史偏离中学习用户偏好，生成趋势报告。

Type corrections (A): 域名→类型覆盖规律
Depth preferences (B): 内容类型→深度偏好
Trend reports (D): 时段统计（类型分布、深度分布、取消率等）

混合模式阈值:
    ≥2 次同方向偏离 → 自动应用
    1 次偏离 → 建议提示
"""

import re
import time
from collections import Counter, defaultdict
from urllib.parse import urlparse

try:
    from ctw_state import RunStore
except ImportError:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))
    from ctw_state import RunStore


def _extract_domain(url: str) -> str:
    if not url:
        return ""
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def _depth_to_int(level: str) -> int:
    m = re.search(r"(\d+)", str(level))
    return int(m.group(1)) if m else 1


def _direction(old: str, new: str) -> str:
    """depth 偏离方向"""
    o, n = _depth_to_int(old), _depth_to_int(new)
    if n > o:
        return "up"
    if n < o:
        return "down"
    return "same"


class PatternAnalyzer:
    """从 RunStore 中分析用户行为模式。

    Usage:
        store = RunStore()
        pa = PatternAnalyzer(store)
        suggestions = pa.get_suggestions(url, content_type, recommended_depth)
        report = pa.generate_trend_report(days=30)
    """

    def __init__(self, store: RunStore = None):
        self.store = store or RunStore()

    # ── A: 类型纠正 ──

    def analyze_type_corrections(self) -> dict:
        """分析域名→类型覆盖规律。

        Returns:
            {domain: {from_type: {to_type: count}}}
        """
        patterns = defaultdict(lambda: defaultdict(Counter))
        for run in self.store.load_deviations():
            url = run.get("url", "")
            domain = _extract_domain(url)
            if not domain:
                continue
            for d in run.get("deviations", []):
                if d.get("axis") != "type":
                    continue
                from_type = d.get("original_value", "")
                to_type = d.get("new_value", "")
                if from_type and to_type and from_type != to_type:
                    patterns[domain][from_type][to_type] += 1
        return {d: dict(f) for d, f in patterns.items()}

    # ── B: 深度偏好 ──

    def analyze_depth_preferences(self) -> dict:
        """分析内容类型→深度偏好规律。

        Returns:
            {content_type: {"up": count, "down": count}}
        """
        prefs = defaultdict(Counter)
        for run in self.store.load_deviations():
            ct = run.get("content_type", "")
            if not ct:
                continue
            for d in run.get("deviations", []):
                if d.get("axis") != "depth":
                    continue
                dir_ = _direction(d.get("original_value", ""), d.get("new_value", ""))
                if dir_ != "same":
                    prefs[ct][dir_] += 1
        return dict(prefs)

    # ── 综合建议入口 ──

    def get_suggestions(self, url: str, content_type: str,
                        recommended_depth: str) -> dict:
        """给定 URL + 分类/深度，返回建议和自动应用决策。

        Returns:
            {
                "type_suggestion": str or None,       # 建议的类型
                "type_auto_apply": bool,               # 是否自动应用
                "type_confidence": int,                # 历史偏离次数
                "depth_suggestion": str or None,       # 建议的深度 (L0-L4)
                "depth_direction": "up" | "down" | None,
                "depth_auto_apply": bool,
                "depth_confidence": int,
            }
        """
        result = {
            "type_suggestion": None,
            "type_auto_apply": False,
            "type_confidence": 0,
            "depth_suggestion": None,
            "depth_direction": None,
            "depth_auto_apply": False,
            "depth_confidence": 0,
        }

        domain = _extract_domain(url)

        # ── 类型纠正 ──
        if domain and content_type:
            corrections = self.analyze_type_corrections()
            domain_patterns = corrections.get(domain, {})
            from_map = domain_patterns.get(content_type, {})
            if from_map:
                best_to = max(from_map, key=from_map.get)
                best_count = from_map[best_to]
                result["type_suggestion"] = best_to
                result["type_confidence"] = best_count
                if best_count >= 2:
                    result["type_auto_apply"] = True

        # ── 深度偏好 ──
        if content_type:
            prefs = self.analyze_depth_preferences()
            ct_prefs = prefs.get(content_type, {})
            if ct_prefs:
                up_count = ct_prefs.get("up", 0)
                down_count = ct_prefs.get("down", 0)
                if up_count > down_count and up_count >= 1:
                    result["depth_direction"] = "up"
                    result["depth_confidence"] = up_count
                    result["depth_suggestion"] = self._adjust_depth(recommended_depth, "up")
                    if up_count >= 2:
                        result["depth_auto_apply"] = True
                elif down_count > up_count and down_count >= 1:
                    result["depth_direction"] = "down"
                    result["depth_confidence"] = down_count
                    result["depth_suggestion"] = self._adjust_depth(recommended_depth, "down")
                    if down_count >= 2:
                        result["depth_auto_apply"] = True

        return result

    def _adjust_depth(self, current: str, direction: str) -> str:
        current_num = _depth_to_int(current)
        if direction == "up":
            return f"L{min(current_num + 1, 4)}"
        else:
            return f"L{max(current_num - 1, 0)}"

    # ── D: 趋势报告 ──

    def generate_trend_report(self, days: int = 30) -> dict:
        """生成时段统计报告。

        Returns:
            {
                "period": "2026-04-21 ~ 2026-05-21",
                "total_runs": 42,
                "complete": 38, "cancelled": 3, "error": 1,
                "type_distribution": {"tool-extension": 15, ...},
                "depth_distribution": {"L1": 20, "L2": 12, ...},
                "avg_confidence": 0.87,
                "total_files_written": 120,
                "deviations_total": 8,
                "deviation_rate": 0.19,
                "top_domains": ["github.com", "arxiv.org"],
                "top_types": ["tool-extension", "paper-review"],
            }
        """
        since = time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400))
        runs = self.store.load_runs(since=since)

        if not runs:
            return {"period": f"{since} ~ {time.strftime('%Y-%m-%d')}",
                    "total_runs": 0}

        status_counts = Counter(r.get("status", "unknown") for r in runs)
        type_counts = Counter(r.get("content_type", "unknown") for r in runs)
        depth_counts = Counter(r.get("recommended_depth", "") for r in runs)
        domain_counts = Counter(_extract_domain(r.get("url", "")) for r in runs)

        confidences = [r.get("confidence", 0) for r in runs if r.get("confidence")]
        deviations_total = sum(len(r.get("deviations", [])) for r in runs)
        files_written = sum(r.get("files_written", 0) for r in runs)

        return {
            "period": f"{since} ~ {time.strftime('%Y-%m-%d')}",
            "total_runs": len(runs),
            "complete": status_counts.get("complete", 0),
            "cancelled": status_counts.get("cancelled", 0),
            "error": status_counts.get("error", 0),
            "type_distribution": dict(type_counts.most_common()),
            "depth_distribution": dict(sorted(depth_counts.items())),
            "avg_confidence": round(sum(confidences) / len(confidences), 3) if confidences else 0,
            "total_files_written": files_written,
            "deviations_total": deviations_total,
            "deviation_rate": round(deviations_total / len(runs), 2),
            "top_domains": [d for d, _ in domain_counts.most_common(5) if d],
            "top_types": [t for t, _ in type_counts.most_common(5)],
        }


# ── 模块级单例 ──

_analyzer: PatternAnalyzer = None


def get_analyzer(store: RunStore = None) -> PatternAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = PatternAnalyzer(store)
    return _analyzer
