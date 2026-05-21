"""CTW Reports — Report generation, chains, and recyclable inputs.

Reports are Markdown files with YAML frontmatter stored in {artifact_repo}/reports/.
They form chains: v1 → v2 → synthesis, all versions preserved.
Reports can become Input Sources for new Processing Runs.
"""
import os
import time
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))
from ctw_types import SourceInput


class ReportGenerator:
    """Generate, chain, and read reports from Processing Runs."""

    def __init__(self, artifact_path):
        self.artifact_path = Path(artifact_path)
        self.reports_dir = self.artifact_path / "reports"
        os.makedirs(self.reports_dir, exist_ok=True)

    def _make_frontmatter(self, data: dict) -> str:
        """Build YAML frontmatter string."""
        lines = ["---"]
        for key, value in data.items():
            if isinstance(value, list):
                items = ", ".join(str(v) for v in value)
                lines.append(f"{key}: [{items}]")
            elif isinstance(value, str) and "\n" in value:
                lines.append(f"{key}: |")
                for line in value.split("\n"):
                    lines.append(f"  {line.strip()}")
            elif isinstance(value, str):
                escaped = value.replace('"', '\\"')
                lines.append(f'{key}: "{escaped}"')
            elif isinstance(value, bool):
                lines.append(f"{key}: {str(value).lower()}")
            else:
                lines.append(f"{key}: {value}")
        lines.append("---\n")
        return "\n".join(lines)

    def generate_report(self, run_result: dict, title: str, request: str,
                        content: str = "") -> dict:
        """Generate a report from a completed Processing Run.

        Args:
            run_result: Dict with run_id and status from execute()
            title: Report title
            request: Human's request description
            content: Optional pre-written content (default: auto-generated placeholder)

        Returns:
            Dict with path, frontmatter, content
        """
        run_id = run_result.get("run_id", time.strftime("%Y%m%d-%H%M%S"))
        created = time.strftime("%Y-%m-%dT%H:%M:%S")

        frontmatter = {
            "type": "report",
            "title": title,
            "run_id": run_id,
            "created": created,
            "status": "draft",
            "chain_position": 1,
            "supersedes": [],
            "references": [run_id],
        }

        if not content:
            content = f"# {title}\n\n## Request\n{request}\n\n## Analysis\n\n_Pending analysis_\n"

        full_content = self._make_frontmatter(frontmatter) + content

        slug = title.lower().replace(" ", "-").replace("'", "")[:80]
        filename = f"{time.strftime('%Y%m%d')}-{slug}.md"
        path = self.reports_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            f.write(full_content)

        return {
            "path": str(path),
            "frontmatter": frontmatter,
            "content": content,
        }

    def generate_report_chain(self, base_report: dict, new_run_result: dict,
                               title: str, request: str, content: str = "") -> dict:
        """Generate v2 of a report, referencing the previous version.

        Args:
            base_report: Previous report dict (from generate_report)
            new_run_result: New run result dict
            title: New report title
            request: Human's request description
            content: Optional content

        Returns:
            New report dict
        """
        run_id = new_run_result.get("run_id", time.strftime("%Y%m%d-%H%M%S"))
        created = time.strftime("%Y-%m-%dT%H:%M:%S")
        base_chain_pos = base_report["frontmatter"].get("chain_position", 1)

        references = [run_id, base_report["frontmatter"]["run_id"]]

        frontmatter = {
            "type": "report",
            "title": title,
            "run_id": run_id,
            "created": created,
            "status": "draft",
            "chain_position": base_chain_pos + 1,
            "supersedes": [],
            "references": references,
        }

        prev_path = base_report.get("path", "unknown")
        if not content:
            content = (
                f"# {title}\n\n"
                f"## Request\n{request}\n\n"
                f"## Previous Version\nSee: {prev_path}\n\n"
                f"## Analysis\n\n_Pending analysis_\n"
            )

        full_content = self._make_frontmatter(frontmatter) + content

        slug = title.lower().replace(" ", "-").replace("'", "")[:80]
        filename = f"{time.strftime('%Y%m%d')}-{slug}.md"
        path = self.reports_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            f.write(full_content)

        return {
            "path": str(path),
            "frontmatter": frontmatter,
            "content": content,
        }

    def generate_synthesis(self, predecessors: list[dict], run_result: dict,
                            title: str, request: str, content: str = "") -> dict:
        """Generate a synthesis report that supersedes all predecessors.

        All predecessor reports are preserved. The synthesis links to them.

        Args:
            predecessors: List of previous report dicts
            run_result: Run result dict
            title: Synthesis report title
            request: Human's request description
            content: Optional content

        Returns:
            Synthesis report dict
        """
        run_id = run_result.get("run_id", time.strftime("%Y%m%d-%H%M%S"))
        created = time.strftime("%Y-%m-%dT%H:%M:%S")

        supersedes = [p["frontmatter"]["run_id"] for p in predecessors]
        references = [run_id] + supersedes

        frontmatter = {
            "type": "report",
            "title": title,
            "run_id": run_id,
            "created": created,
            "status": "draft",
            "chain_position": "synthesis",
            "supersedes": supersedes,
            "references": references,
        }

        prev_sections = ""
        for p in predecessors:
            p_path = p.get("path", "unknown")
            p_title = p["frontmatter"].get("title", "Unknown")
            prev_sections += f"- [{p_title}]({p_path})\n"

        if not content:
            content = (
                f"# {title}\n\n"
                f"## Request\n{request}\n\n"
                f"## Synthesized From\n{prev_sections}\n\n"
                f"## Synthesis\n\n_Pending synthesis_\n"
            )

        full_content = self._make_frontmatter(frontmatter) + content

        slug = title.lower().replace(" ", "-").replace("'", "")[:80]
        filename = f"{time.strftime('%Y%m%d')}-synthesis-{slug}.md"
        path = self.reports_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            f.write(full_content)

        return {
            "path": str(path),
            "frontmatter": frontmatter,
            "content": content,
        }

    def report_as_source_input(self, report_path: str) -> SourceInput:
        """Read a report file and return it as a SourceInput for the pipeline.

        Reports become Input Sources for new Processing Runs.
        """
        with open(report_path, "r", encoding="utf-8") as f:
            raw = f.read()

        # Parse frontmatter
        title = "Untitled Report"
        if raw.startswith("---"):
            parts = raw.split("---", 2)
            if len(parts) >= 3:
                fm_text = parts[1]
                for line in fm_text.split("\n"):
                    if line.startswith("title:"):
                        title = line.split(":", 1)[1].strip().strip('"')

        content = raw[:5000]  # Truncate to manageable size

        return SourceInput(
            url=f"file://{report_path}",
            title=title,
            description=f"Report: {title}",
            content=content,
            source_type="report",
        )
