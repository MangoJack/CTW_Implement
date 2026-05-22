#!/usr/bin/env python3
"""CTW Implement — one-command setup (initial install) and update (existing install).

Usage:
    python deploy.py              # update existing deployment (or guided first-time)
    python deploy.py --fresh      # force fresh/setup mode
    python deploy.py --check      # health-check only, no changes
    python deploy.py --no-tests   # skip test suite (faster)

All paths are auto-detected. See --help for env var overrides.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path helpers — everything relative to this script or user home
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent

# Environment variable overrides (see --help)
ENV_PROJECT_PATH = os.environ.get("CTW_PROJECT_PATH", "")
ENV_REPO_PATH = os.environ.get("CTW_REPO_PATH", "")
ENV_LLM_MODEL = os.environ.get("CTW_LLM_MODEL", "")


def _available_drives() -> list[Path]:
    """Return available drive roots. On non-Windows this is just ['/']."""
    if sys.platform == "win32":
        import string, ctypes
        drives = []
        try:
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            for letter in string.ascii_uppercase:
                if bitmask & 1:
                    drives.append(Path(f"{letter}:\\"))
                bitmask >>= 1
        except Exception:
            drives = [Path.home().anchor]
        return drives
    return [Path("/")]


def find_workspace() -> Path:
    """Auto-detect the agent workspace directory.

    Priority: CTW_PROJECT_PATH env var -> ~/agents/ips-agent ->
    :\\agents\\ips-agent on each available drive (Windows).
    Returns the best available workspace, preferring ones with CONTEXT.md.
    """
    default = Path.home() / "agents" / "ips-agent"
    candidates: list[Path] = []

    if ENV_PROJECT_PATH:
        candidates.append(Path(ENV_PROJECT_PATH))
    if default not in candidates:
        candidates.append(default)

    # Add drive roots for Windows
    for drive in _available_drives():
        p = drive / "agents" / "ips-agent"
        if p not in candidates:
            candidates.append(p)

    # Prefer workspaces with CONTEXT.md (sign of a real deployment)
    best = None
    for p in candidates:
        if (p / "templates" / "taxonomy" / "types.yaml").exists():
            if (p / "CONTEXT.md").exists():
                return p  # complete workspace found
            if best is None:
                best = p  # partial workspace, keep as fallback

    return best or default


# Resolve workspace lazily at first use
_workspace_cached: Path | None = None


def get_workspace() -> Path:
    global _workspace_cached
    if _workspace_cached is None:
        _workspace_cached = find_workspace()
    return _workspace_cached


# ---------------------------------------------------------------------------
# Workspace scaffolding
# ---------------------------------------------------------------------------

WORKSPACE_LAYOUT: dict[str, list[str]] = {
    # directory                  files that must exist inside it
    "": [                         # workspace root
        "config.md",
        "CONTEXT.md",
        "FAIR.md",
        "ctw-design-philosophy.md",
    ],
    "state": [],
    "state/runs": [],
    "raw": [],
    "wiki/sources": [],
    "wiki/entities": [],
    "wiki/concepts": [],
    "wiki/comparisons": [],
    "zettelkasten/2-permanent": [],
    "reports": [],
    "templates/taxonomy": ["types.yaml"],
    "templates/workflows": ["gates.yaml"],
    "templates/infolevel": [
        "LEVELS.md", "README.md",
    ],
    "templates/llmwiki/templates": [
        "source-summary.md", "entity.md", "concept.md",
        "comparison.md", "recommendation.md",
    ],
    "templates/zettelkasten/templates": [
        "permanent-note.md", "moc-note.md", "book-note.md",
        "person-note.md", "term-note.md",
    ],
}


def find_template_source() -> Path | None:
    """Locate an existing workspace with templates we can copy from.
    Searches the same paths as find_workspace() plus the current workspace.
    """
    candidates = [get_workspace()]
    for drive in _available_drives():
        p = drive / "agents" / "ips-agent"
        if p not in candidates:
            candidates.append(p)
    for p in candidates:
        if (p / "templates" / "taxonomy" / "types.yaml").exists():
            return p
    return None


def ensure_workspace(workspace: Path, template_src: Path | None) -> dict[str, int]:
    """Create workspace directory structure. Copy missing files from template source.
    Returns {path: action} where action is 0=exists, 1=created, 2=copied.
    """
    report: dict[str, int] = {}

    for subdir, files in WORKSPACE_LAYOUT.items():
        d = workspace / subdir if subdir else workspace
        d.mkdir(parents=True, exist_ok=True)

        for fname in files:
            target = d / fname
            if target.exists():
                report[str(target)] = 0  # already exists
                continue

            # Attempt to copy from template source
            src = None
            if template_src:
                candidate = template_src / subdir / fname if subdir else template_src / fname
                # Also try templates/ prefix
                candidate2 = template_src / "templates" / subdir / fname if subdir else template_src / "templates" / fname
                for c in (candidate, candidate2):
                    if c.exists():
                        src = c
                        break

            if src:
                target.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
                report[str(target)] = 2  # copied
            else:
                target.write_text("", encoding="utf-8")
                report[str(target)] = 1  # created empty

    return report


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def write_settings(repo_path: str | None = None) -> Path:
    """Write (or update) config/settings.yaml with the artifact repository path."""
    settings_dir = PROJECT_ROOT / "config"
    settings_dir.mkdir(parents=True, exist_ok=True)
    settings_file = settings_dir / "settings.yaml"

    current = {}
    if settings_file.exists():
        import yaml
        try:
            current = yaml.safe_load(settings_file.read_text(encoding="utf-8")) or {}
        except Exception:
            pass

    if repo_path:
        current["repository_path"] = repo_path
    elif "repository_path" not in current:
        current["repository_path"] = ""

    settings_file.write_text(
        f"repository_path: {current['repository_path']}\n", encoding="utf-8"
    )
    return settings_file


# ---------------------------------------------------------------------------
# Verification steps (return True on pass)
# ---------------------------------------------------------------------------

class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    RESET = "\033[0m"


def ok(msg: str) -> str:
    return f"{Colors.GREEN}{msg}{Colors.RESET}"


def fail(msg: str) -> str:
    return f"{Colors.RED}{msg}{Colors.RESET}"


def warn(msg: str) -> str:
    return f"{Colors.YELLOW}{msg}{Colors.RESET}"


def check_python() -> bool:
    v = sys.version_info
    ok_ = v >= (3, 10)
    label = f"Python {v.major}.{v.minor}.{v.micro}"
    print(f"  {label:40s}", ok("OK") if ok_ else fail(f"need >= 3.10"))
    return ok_


def check_pyyaml() -> bool:
    try:
        import yaml
        print(f"  {'pyyaml ' + yaml.__version__:40s}", ok("OK"))
        return True
    except ImportError:
        print(f"  {'pyyaml':40s}", fail("not installed"))
        return False


def check_workspace(workspace: Path) -> bool:
    missing = []
    for subdir, files in WORKSPACE_LAYOUT.items():
        d = workspace / subdir if subdir else workspace
        for fname in files:
            if not (d / fname).exists():
                missing.append(str(d / fname))

    label = f"Workspace ({len(missing)} missing)"
    if missing:
        print(f"  {label:40s}", warn(f"{len(missing)} files missing"))
        for m in missing[:5]:
            print(f"    - {Path(m).name}")
        if len(missing) > 5:
            print(f"    ... and {len(missing) - 5} more")
        return False
    print(f"  {label:40s}", ok("OK"))
    return True


def check_repo_path() -> bool:
    settings_file = PROJECT_ROOT / "config" / "settings.yaml"
    path = ""
    if settings_file.exists():
        import yaml
        try:
            cfg = yaml.safe_load(settings_file.read_text(encoding="utf-8")) or {}
            path = cfg.get("repository_path", "")
        except Exception:
            pass

    exists = bool(path and Path(path).exists())
    label = f"Artifact repo ({path[:50]}{'...' if len(path) > 50 else ''})"
    print(f"  {label:40s}", ok("reachable") if exists else warn("not set or unreachable"))
    return exists


def check_llm() -> bool:
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "lib"))
        from ctw_llm import LLMClient
        c = LLMClient()
        label = f"LLM ({c.model})"
        if not c.api_key:
            print(f"  {label:40s}", fail("no API key"))
            return False
        print(f"  {label:40s}", ok(f"key=sk-...{c.api_key[-4:]}"))
        return True
    except Exception as e:
        print(f"  {'LLM':40s}", fail(str(e)[:50]))
        return False


def check_tests() -> bool:
    print("  Running tests ...", end=" ", flush=True)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "skills/", "tests/", "-q", "--tb=short"],
            cwd=str(PROJECT_ROOT),
            capture_output=True, text=True, timeout=600,
        )
        if result.returncode == 0:
            # Extract "N passed" from last line
            last = [l for l in result.stdout.strip().split("\n") if l][-1]
            print(ok(last))
            return True
        else:
            print(fail("failures"))
            print(result.stdout[-500:])
            print(result.stderr[-500:])
            return False
    except subprocess.TimeoutExpired:
        print(fail("timeout"))
        return False
    except Exception as e:
        print(fail(str(e)))
        return False


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_fresh(workspace: Path, repo_path: str | None, run_tests: bool = True) -> int:
    """First-time deployment."""
    print("=== CTW Deploy: Fresh Setup ===\n")

    # 1. Preflight
    print("[1/5] Preflight checks")
    py_ok = check_python()
    yaml_ok = check_pyyaml()
    if not py_ok or not yaml_ok:
        print(fail("\nPrerequisites not met. Install Python >= 3.10 and run: pip install pyyaml"))
        return 1
    if not yaml_ok:
        print("  Installing pyyaml ...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyyaml>=6.0"], check=True)
        print(f"  {'pyyaml':40s}", ok("installed"))

    # 2. Workspace
    print("\n[2/5] Workspace setup")
    template_src = find_template_source()
    if template_src:
        print(f"  Template source: {template_src}")
    else:
        print(f"  {warn('No template source found — workspace files will be empty stubs.')}")
    report = ensure_workspace(workspace, template_src)
    created = sum(1 for v in report.values() if v > 0)
    existed = sum(1 for v in report.values() if v == 0)
    print(f"  {existed} files present, {created} created")

    # 3. Configuration
    print("\n[3/5] Configuration")
    effective_repo = repo_path or ENV_REPO_PATH
    if not effective_repo:
        effective_repo = input("  Artifact repository path (NAS or local): ").strip()
    settings = write_settings(effective_repo)
    print(f"  {settings}: repository_path = {effective_repo}")
    if effective_repo and Path(effective_repo).exists():
        print(f"  {ok('Path is reachable')}")

    # 4. LLM
    print("\n[4/5] LLM connectivity")
    check_llm()

    # 5. Tests
    print("\n[5/5] Tests")
    if run_tests:
        check_tests()
    else:
        print("  Skipped (--no-tests)")

    print(f"\n{ok('Deploy complete.')} Workspace: {workspace}")
    return 0


def cmd_update(workspace: Path, repo_path: str | None, run_tests: bool = True) -> int:
    """Update an existing deployment."""
    print("=== CTW Deploy: Update ===\n")

    print("[1/4] Verify workspace")
    ws_ok = check_workspace(workspace)
    if not ws_ok:
        print("  Repairing ...")
        template_src = find_template_source()
        ensure_workspace(workspace, template_src)

    print("\n[2/4] Configuration")
    if repo_path or ENV_REPO_PATH:
        effective = repo_path or ENV_REPO_PATH
        write_settings(effective)
        print(f"  repository_path = {effective}")
    check_repo_path()

    print("\n[3/4] LLM")
    check_llm()

    print("\n[4/4] Tests")
    if run_tests:
        check_tests()
    else:
        print("  Skipped (--no-tests)")

    print(f"\n{ok('Update complete.')}")
    return 0


def cmd_check(workspace: Path) -> int:
    """Health-check only, no modifications."""
    print("=== CTW Deploy: Health Check ===\n")
    all_ok = True
    all_ok &= check_python()
    all_ok &= check_pyyaml()
    all_ok &= check_workspace(workspace)
    all_ok &= check_repo_path()
    all_ok &= check_llm()
    print()
    if all_ok:
        print(ok("All checks passed."))
    else:
        print(warn("Some checks failed. Run 'python deploy.py' to repair."))
    return 0 if all_ok else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(
        description="CTW Implement — deployment & maintenance script",
        epilog="""
Environment variables (all optional — script auto-detects):
  CTW_PROJECT_PATH   Agent workspace path         (default: ~/agents/ips-agent)
  CTW_REPO_PATH      Artifact repository path     (default: prompt interactively)
  CTW_LLM_MODEL      Override LLM model ID        (default: from openclaw.json)
  CTW_LLM_API_KEY    Override LLM API key         (default: from openclaw.json)
""",
    )
    p.add_argument("--workspace", "-w",
                   help="Agent workspace path (default: auto-detect ~/agents/ips-agent or "
                        "drive:\\agents\\ips-agent)")
    p.add_argument("--repo", "-r",
                   help="Artifact repository path (NAS or local)")
    p.add_argument("--fresh", action="store_true",
                   help="Force fresh/setup mode instead of update")
    p.add_argument("--check", action="store_true",
                   help="Health-check only, no changes")
    p.add_argument("--no-tests", action="store_true",
                   help="Skip test suite (faster)")
    args = p.parse_args()

    workspace = Path(args.workspace) if args.workspace else get_workspace()
    repo_path = args.repo or None  # None means "don't change / auto-detect"

    if args.check:
        sys.exit(cmd_check(workspace))

    is_fresh = args.fresh or not workspace.exists() or not (workspace / "templates").exists()
    if is_fresh:
        sys.exit(cmd_fresh(workspace, repo_path, not args.no_tests))
    else:
        sys.exit(cmd_update(workspace, repo_path, not args.no_tests))


if __name__ == "__main__":
    main()
