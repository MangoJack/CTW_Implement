# CTW Implement — 配置加载器
"""
加载和解析 CTW 配置，包括 taxonomy/types.yaml、infolevel/LEVELS.md、
workflows/gates.yaml、maintenance/lifecycle.yaml 等。

配置优先级:
  1. 环境变量 CTW_REPO_PATH (最高)
  2. config/settings.yaml 中的 repository_path
  3. 未配置 → 拒绝写入，需人类先指定
"""
import yaml
import os
from pathlib import Path
from typing import Any, Optional

from ctw_types import ContentType, InfoLevel, ValueQuestion


class CTWConfig:
    """CTW 全局配置管理器"""

    # 配置文件路径（相对于 CTW_Implement 根目录）
    SETTINGS_FILE = "config/settings.yaml"

    def __init__(self, ctw_implement_path: str = None, ctw_project_path: str = None):
        if ctw_implement_path:
            self.implement_path = Path(ctw_implement_path)
        else:
            self.implement_path = Path(os.environ.get(
                "CTW_IMPLEMENT_PATH",
                os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."),
            ))

        if ctw_project_path:
            self.project_path = Path(ctw_project_path)
        else:
            self.project_path = Path(os.environ.get(
                "CTW_PROJECT_PATH",
                "D:\\MainWorkSpace\\contextToWhatend"
            ))

        self.types: dict = {}
        self.infolevel: dict = {}
        self.gates: dict = {}
        self.lifecycle: dict = {}
        self._loaded = False

        # 仓库路径（人类指定，产出文件写入此处）
        self._repository_path: Optional[Path] = None
        self._load_settings()

    # ── 仓库路径管理 ──

    @property
    def repository_path(self) -> Optional[Path]:
        """获取产出仓库路径。未配置时返回 None。"""
        if self._repository_path:
            return self._repository_path
        return None

    @property
    def has_repository(self) -> bool:
        """检查仓库路径是否已配置。"""
        return self._repository_path is not None and self._repository_path.is_dir() if self._repository_path else False

    def set_repository(self, path: str) -> Path:
        """设置产出仓库路径并持久化到 settings.yaml。

        Args:
            path: 仓库目录路径（可以是 NAS 路径、本地路径等）

        Returns:
            设置的 Path 对象

        Raises:
            NotADirectoryError: 路径不存在
        """
        repo = Path(path)
        if not repo.exists():
            os.makedirs(repo, exist_ok=True)
        if not repo.is_dir():
            raise NotADirectoryError(f"路径不是目录: {path}")

        self._repository_path = repo.resolve()
        self._save_settings()
        return self._repository_path

    def require_repository(self) -> Path:
        """获取仓库路径；未配置时抛出异常。

        Returns:
            仓库路径
        Raises:
            RuntimeError: 仓库路径未配置
        """
        if not self._repository_path:
            raise RuntimeError(
                "产出仓库路径未配置。请先运行:\n"
                "  python ctw_runner.py repo --set <路径>\n"
                "  或设置环境变量 CTW_REPO_PATH"
            )
        return self._repository_path

    @staticmethod
    def resolve_settings_file() -> Path:
        """解析 settings.yaml 的绝对路径。"""
        return Path(os.environ.get(
            "CTW_IMPLEMENT_PATH",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."),
        )) / "config" / "settings.yaml"

    def _load_settings(self) -> None:
        """从 config/settings.yaml 加载配置。"""
        settings_path = self.implement_path / self.SETTINGS_FILE

        if not settings_path.exists():
            # 尝试从环境变量 CTW_REPO_PATH 获取仓库路径
            env_repo = os.environ.get("CTW_REPO_PATH", "")
            if env_repo:
                repo = Path(env_repo)
                if repo.is_dir():
                    self._repository_path = repo.resolve()
            return

        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            data = {}

        repo_path = data.get("repository_path", "")
        if repo_path:
            repo = Path(repo_path)
            if repo.is_dir():
                self._repository_path = repo.resolve()

        # 环境变量覆盖文件配置
        env_repo = os.environ.get("CTW_REPO_PATH", "")
        if env_repo:
            repo = Path(env_repo)
            if repo.is_dir():
                self._repository_path = repo.resolve()

    def _save_settings(self) -> None:
        """持久化配置到 config/settings.yaml。"""
        settings_path = self.implement_path / self.SETTINGS_FILE

        # 保留已有配置
        existing = {}
        if settings_path.exists():
            try:
                with open(settings_path, "r", encoding="utf-8") as f:
                    existing = yaml.safe_load(f) or {}
            except Exception:
                pass

        existing["repository_path"] = str(self._repository_path) if self._repository_path else ""

        os.makedirs(settings_path.parent, exist_ok=True)
        with open(settings_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(existing, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    # ── 原始配置加载 ──

    def load_all(self) -> None:
        self._load_taxonomy()
        self._load_gates()
        self._loaded = True

    def _load_taxonomy(self) -> None:
        path = self.project_path / "taxonomy" / "types.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Taxonomy config not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.types = data.get("types", {})
        self.decision_tree = data.get("decision_tree", {})

    def _load_gates(self) -> None:
        path = self.project_path / "workflows" / "gates.yaml"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            self.gates = data.get("gates", {})
            self.chains = data.get("chains", {})
            self.overrides = data.get("overrides", {})

    def get_type(self, type_id: str) -> dict:
        if not self._loaded:
            self.load_all()
        return self.types.get(type_id, {})

    def get_all_types(self) -> dict:
        if not self._loaded:
            self.load_all()
        return self.types

    def get_chain(self, level: InfoLevel) -> list:
        if not self._loaded:
            self.load_all()
        key = f"{level.value.lower()}_chain"
        return self.chains.get(key, [])

    # ── ZK notes path helper ──

    def get_output_path(self, category: str) -> Path:
        """获取指定类别的产出目录路径（在仓库下）。

        Args:
            category: 目录类别，如 'sources', 'entities', 'concepts', 'comparisons', 'zk'

        Returns:
            完整路径
        """
        repo = self.require_repository()
        if category == "zk":
            return repo / "zk"
        return repo / "wiki" / category

    def status_dict(self) -> dict:
        """获取配置状态字典（供 CLI status 命令使用）。"""
        return {
            "implement_path": str(self.implement_path),
            "project_path": str(self.project_path),
            "repository_path": str(self._repository_path) if self._repository_path else "未配置",
            "has_repository": self.has_repository,
            "types_loaded": self._loaded,
            "types_count": len(self.types) if self.types else 0,
        }
