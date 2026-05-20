# -*- coding: utf-8 -*-
"""
CTW InfoLevel Router Tests

Test-driven: these tests define the contract before router.py is implemented.
"""
import sys
import os

# --- Path setup ---
_tests_dir = os.path.dirname(os.path.abspath(__file__))
_skill_dir = os.path.dirname(_tests_dir)
_implement_dir = os.path.dirname(os.path.dirname(_skill_dir))
_lib_dir = os.path.join(_implement_dir, "lib")

sys.path.insert(0, _lib_dir)
sys.path.insert(0, _skill_dir)

from ctw_types import ContentType, InfoLevel, ClassifyResult, LevelResult
from router import InfoLevelRouter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(content_type: ContentType, confidence: float = 0.85,
                 reason: str = "auto-classified") -> ClassifyResult:
    """Factory: create a minimal realistic ClassifyResult for tests."""
    return ClassifyResult(
        content_type=content_type,
        content_type_name=content_type.value,
        confidence=confidence,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestInfoLevelRouter:
    """Test suite for the InfoLevelRouter."""

    # ── setup ──────────────────────────────────────────────────────────

    def setup_method(self):
        self.router = InfoLevelRouter()

    # ── default-level tests ────────────────────────────────────────────

    def test_default_level_tool_extension(self):
        """tool-extension → L1 (Tool Review)."""
        cr = _make_result(ContentType.TOOL_EXTENSION)
        out = self.router.route(cr)
        assert out.level == InfoLevel.L1

    def test_default_level_tool_review(self):
        """tool-review → L1."""
        cr = _make_result(ContentType.TOOL_REVIEW)
        out = self.router.route(cr)
        assert out.level == InfoLevel.L1

    def test_default_level_practice_tutorial(self):
        """practice-tutorial → L2."""
        cr = _make_result(ContentType.PRACTICE_TUTORIAL)
        out = self.router.route(cr)
        assert out.level == InfoLevel.L2

    def test_default_level_architecture_analysis(self):
        """architecture-analysis → L3."""
        cr = _make_result(ContentType.ARCHITECTURE_ANALYSIS)
        out = self.router.route(cr)
        assert out.level == InfoLevel.L3

    def test_default_level_paper_review(self):
        """paper-review → L4."""
        cr = _make_result(ContentType.PAPER_REVIEW)
        out = self.router.route(cr)
        assert out.level == InfoLevel.L4

    def test_default_level_tech_news(self):
        """tech-news → L0 (Quick Scan)."""
        cr = _make_result(ContentType.TECH_NEWS)
        out = self.router.route(cr)
        assert out.level == InfoLevel.L0

    def test_default_level_experience_share(self):
        """experience-share → L1."""
        cr = _make_result(ContentType.EXPERIENCE_SHARE)
        out = self.router.route(cr)
        assert out.level == InfoLevel.L1

    def test_default_level_spec_standard(self):
        """spec-standard → L4."""
        cr = _make_result(ContentType.SPEC_STANDARD)
        out = self.router.route(cr)
        assert out.level == InfoLevel.L4

    def test_default_level_security_research(self):
        """security-research → L1."""
        cr = _make_result(ContentType.SECURITY_RESEARCH)
        out = self.router.route(cr)
        assert out.level == InfoLevel.L1

    def test_default_level_ai_agent(self):
        """ai-agent → L2."""
        cr = _make_result(ContentType.AI_AGENT)
        out = self.router.route(cr)
        assert out.level == InfoLevel.L2

    def test_default_level_unknown(self):
        """unknown type → L1 (safe default)."""
        cr = _make_result(ContentType.UNKNOWN)
        out = self.router.route(cr)
        assert out.level == InfoLevel.L1

    # ── manual override tests ──────────────────────────────────────────

    def test_manual_override_upgrade(self):
        """User upgrades tool-extension L1 → L2 (within max L3)."""
        cr = _make_result(ContentType.TOOL_EXTENSION)
        out = self.router.route(cr, manual_override=InfoLevel.L2)
        assert out.level == InfoLevel.L2

    def test_manual_override_downgrade(self):
        """User downgrades paper-review L4 → L3."""
        cr = _make_result(ContentType.PAPER_REVIEW)
        out = self.router.route(cr, manual_override=InfoLevel.L3)
        assert out.level == InfoLevel.L3

    def test_cannot_upgrade_beyond_max(self):
        """tool-review max=L2; upgrading to L3 should fall back to default."""
        cr = _make_result(ContentType.TOOL_REVIEW)
        out = self.router.route(cr, manual_override=InfoLevel.L3)
        assert out.level == InfoLevel.L1

    # ── can_upgrade tests ──────────────────────────────────────────────

    def test_can_upgrade_to_L4_ai_agent(self):
        """ai-agent has max L4, so L2 → L4 upgrade is allowed."""
        assert self.router.can_upgrade(
            InfoLevel.L2, InfoLevel.L4, ContentType.AI_AGENT
        )

    def test_can_upgrade_tech_news_beyond_L1_fails(self):
        """tech-news max is L1, can't upgrade to L2."""
        assert not self.router.can_upgrade(
            InfoLevel.L0, InfoLevel.L2, ContentType.TECH_NEWS
        )

    def test_can_upgrade_same_level(self):
        """Staying at same level always ok."""
        assert self.router.can_upgrade(
            InfoLevel.L2, InfoLevel.L2, ContentType.PRACTICE_TUTORIAL
        )

    def test_can_upgrade_downgrade_always(self):
        """Downgrade is always allowed regardless of max."""
        assert self.router.can_upgrade(
            InfoLevel.L4, InfoLevel.L1, ContentType.TECH_NEWS
        )

    # ── result quality tests ───────────────────────────────────────────

    def test_level_description_included(self):
        """L2 result should contain a non-empty reason string."""
        cr = _make_result(ContentType.PRACTICE_TUTORIAL)
        out = self.router.route(cr)
        assert out.level == InfoLevel.L2
        assert isinstance(out.reason, str)
        assert len(out.reason) > 0
        assert "L2" in out.reason or "实践" in out.reason

    def test_result_has_template(self):
        """Every LevelResult should include a template path."""
        cr = _make_result(ContentType.TOOL_EXTENSION)
        out = self.router.route(cr)
        assert len(out.template) > 0
        assert "l1" in out.template.lower()

    def test_result_has_level_name(self):
        """LevelResult.level_name should match level.value."""
        cr = _make_result(ContentType.ARCHITECTURE_ANALYSIS)
        out = self.router.route(cr)
        assert out.level_name == InfoLevel.L3.value

    # ── edge cases ─────────────────────────────────────────────────────

    def test_router_with_partial_classify(self):
        """Router handles a default-constructed ClassifyResult gracefully."""
        result = ClassifyResult()  # all defaults
        out = self.router.route(result)
        assert out.level is not None
        assert out.level in InfoLevel
        assert isinstance(out.reason, str)

    def test_router_override_to_higher_same_as_max(self):
        """Override to exactly the max level should succeed."""
        cr = _make_result(ContentType.TOOL_EXTENSION)
        out = self.router.route(cr, manual_override=InfoLevel.L3)
        assert out.level == InfoLevel.L3  # max for tool-extension is L3

    def test_router_confidence_preserved(self):
        """Confidence from ClassifyResult should carry through."""
        cr = _make_result(ContentType.AI_AGENT, confidence=0.92)
        out = self.router.route(cr)
        assert out.confidence == 0.92

    def test_cannot_upgrade_unknown_beyond_L2(self):
        """unknown type has a sensible max (L2)."""
        assert not self.router.can_upgrade(
            InfoLevel.L1, InfoLevel.L3, ContentType.UNKNOWN
        )


# ---------------------------------------------------------------------------
# Standalone runner (in case pytest is not the launcher)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
