# CTW Implement — 模板引擎
"""
LLM Wiki 页面模板渲染引擎。
从 llmwiki/templates/ 加载 Jinja2 模板并根据数据渲染。
"""
import os
from pathlib import Path
from typing import Any, Optional


class TemplateEngine:
    """LLM Wiki 页面模板引擎"""

    TEMPLATES = {
        "source_summary": "source-summary.md",
        "entity": "entity.md",
        "concept": "concept.md",
        "comparison": "comparison.md",
    }

    def __init__(self, ctw_project_path: str = None):
        if ctw_project_path:
            self.project_path = Path(ctw_project_path)
        else:
            self.project_path = Path(os.environ.get(
                "CTW_PROJECT_PATH",
                "D:\\MainWorkSpace\\contextToWhatend"
            ))
        self.template_dir = self.project_path / "llmwiki" / "templates"

    def get_template_path(self, template_name: str) -> Optional[Path]:
        """获取模板文件路径"""
        key = self.TEMPLATES.get(template_name, template_name)
        if not key.endswith(".md"):
            key += ".md"
        path = self.template_dir / key
        return path if path.exists() else None

    def read_template(self, template_name: str) -> str:
        """读取模板内容"""
        path = self.get_template_path(template_name)
        if not path:
            raise FileNotFoundError(f"Template not found: {template_name}")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def render_frontmatter(self, data: dict) -> str:
        """渲染 YAML frontmatter"""
        lines = ["---"]
        for key, value in data.items():
            if isinstance(value, list):
                lines.append(f"{key}: [{', '.join(str(v) for v in value)}]")
            elif isinstance(value, str) and "\n" in value:
                lines.append(f"{key}: >")
                for line in value.split("\n"):
                    lines.append(f"  {line}")
            elif isinstance(value, str):
                lines.append(f'{key}: "{value}"')
            else:
                lines.append(f"{key}: {value}")
        lines.append("---\n")
        return "\n".join(lines)

    def render_source_summary(self, data: dict) -> str:
        """渲染源摘要页"""
        fm = {
            "type": "source-summary",
            "source_file": data.get("source_file", ""),
            "source_type": data.get("source_type", ""),
            "title": data.get("title", ""),
            "author": data.get("author", ""),
            "date_read": data.get("date_read", ""),
            "created": data.get("created", ""),
            "updated": data.get("updated", ""),
            "sources": data.get("sources", []),
            "status": data.get("status", "draft"),
            "tags": data.get("tags", []),
            "key_entities": data.get("key_entities", []),
            "key_concepts": data.get("key_concepts", []),
            "provenance_state": data.get("provenance_state", "extracted"),
            "confidence": data.get("confidence", 0.7),
        }
        body = f"# {data.get('title', 'Untitled')}\n\n"
        body += f"> 来源：`{data.get('source_file', '')}`"
        body += f" | 类型：{data.get('source_type', '')}"
        body += f" | 作者：{data.get('author', '')}"
        body += f" | 阅读日期：{data.get('date_read', '')}\n\n"
        body += "## 核心论点\n\n"
        for i, claim in enumerate(data.get("claims", [])[:5], 1):
            body += f"{i}. {claim}\n"
        body += "\n## 摘要\n\n"
        body += data.get("summary", "_待补充_") + "\n\n"
        body += "## 关键概念\n\n"
        for concept in data.get("concepts", []):
            body += f"- [[concepts/{concept}]]\n"
        body += "\n## ZK 原子化候选清单\n\n"
        for candidate in data.get("zk_candidates", []):
            body += f"- [ ] {candidate}\n"
        return self.render_frontmatter(fm) + body
