"""Unit tests for pure/isolated functions across all scripts.

These tests focus on individual function behavior in isolation,
independent of file I/O or external state.
"""

import math
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


# ===========================================================================
# lifecycle_state — pure functions
# ===========================================================================
class TestNowIso:
    def test_returns_string(self):
        from lifecycle_state import now_iso
        result = now_iso()
        assert isinstance(result, str)

    def test_parseable_as_datetime(self):
        from lifecycle_state import now_iso
        dt = datetime.fromisoformat(now_iso())
        assert dt.tzinfo is not None  # Should be timezone-aware

    def test_is_utc(self):
        from lifecycle_state import now_iso
        dt = datetime.fromisoformat(now_iso())
        assert dt.tzinfo == timezone.utc


class TestAllowedTransitions:
    def test_all_phases_have_transitions_defined(self):
        from lifecycle_state import VALID_PHASES, ALLOWED_TRANSITIONS
        for phase in VALID_PHASES:
            assert phase in ALLOWED_TRANSITIONS

    def test_churned_is_terminal(self):
        from lifecycle_state import ALLOWED_TRANSITIONS
        assert ALLOWED_TRANSITIONS["CHURNED"] == set()

    def test_transition_targets_are_valid_phases(self):
        from lifecycle_state import VALID_PHASES, ALLOWED_TRANSITIONS
        for source, targets in ALLOWED_TRANSITIONS.items():
            for target in targets:
                assert target in VALID_PHASES, f"{source} -> {target}: target is not a valid phase"

    def test_no_self_transitions(self):
        from lifecycle_state import ALLOWED_TRANSITIONS
        for phase, targets in ALLOWED_TRANSITIONS.items():
            assert phase not in targets, f"{phase} allows self-transition"


# ===========================================================================
# gap_analysis — pure functions
# ===========================================================================
class TestComputeActivityMatchUnit:
    def test_returns_float(self):
        from gap_analysis import compute_activity_match
        result = compute_activity_match(
            {"name": "test", "why": "reason", "type": "t", "steps": "s"},
            Counter({"test": 5})
        )
        assert isinstance(result, float)

    def test_zero_for_all_stopwords(self):
        from gap_analysis import compute_activity_match
        result = compute_activity_match(
            {"name": "the", "why": "and for", "type": "with", "steps": "from"},
            Counter({"the": 100, "and": 100})
        )
        assert result == 0.0

    def test_short_words_ignored(self):
        """Words shorter than 3 chars should be excluded from matching."""
        from gap_analysis import compute_activity_match
        result = compute_activity_match(
            {"name": "ab", "why": "cd", "type": "ef", "steps": "gh"},
            Counter({"ab": 100, "cd": 100})
        )
        # All words are < 3 chars, so no match
        assert result == 0.0


class TestExtractSkillNameUnit:
    def test_handles_single_quotes(self, tmp_path):
        from gap_analysis import extract_skill_name
        p = tmp_path / "SKILL.md"
        p.write_text("---\nname: 'single-quoted'\ndescription: x\n---\n")
        assert extract_skill_name(p) == "single-quoted"

    def test_handles_whitespace(self, tmp_path):
        from gap_analysis import extract_skill_name
        p = tmp_path / "SKILL.md"
        p.write_text("---\nname:   spaced-name   \ndescription: x\n---\n")
        assert extract_skill_name(p) == "spaced-name"


# ===========================================================================
# churn_decision — pure functions
# ===========================================================================
class TestDaysSinceUnit:
    def test_returns_integer(self):
        from churn_decision import days_since
        ts = datetime.now(timezone.utc).isoformat()
        result = days_since(ts)
        assert isinstance(result, int)
        assert result == 0

    def test_future_date_returns_negative(self):
        from churn_decision import days_since
        future = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
        result = days_since(future)
        assert result < 0

    def test_empty_string(self):
        from churn_decision import days_since
        assert days_since("") is None


class TestIsF1DecliningUnit:
    def test_exactly_at_min_audits(self):
        from churn_decision import is_f1_declining
        history = [{"trigger_f1": 0.9}, {"trigger_f1": 0.8}, {"trigger_f1": 0.7}]
        assert is_f1_declining(history, min_audits=3) is True

    def test_empty_history(self):
        from churn_decision import is_f1_declining
        assert is_f1_declining([], min_audits=3) is False

    def test_single_drop(self):
        """A single audit can't show a trend."""
        from churn_decision import is_f1_declining
        assert is_f1_declining([{"trigger_f1": 0.5}], min_audits=1) is True

    def test_mixed_none_values_insufficient(self):
        from churn_decision import is_f1_declining
        history = [{"trigger_f1": None}, {"trigger_f1": 0.8}, {"trigger_f1": 0.7}]
        assert is_f1_declining(history, min_audits=3) is False


# ===========================================================================
# churn_decision — threshold boundary tests
# ===========================================================================
class TestChurnThresholdBoundaries:
    def test_f1_exactly_at_broken_threshold(self):
        from churn_decision import decide, F1_BROKEN
        skill = {
            "name": "edge", "phase": "DEPLOYED",
            "test_results": {"trigger_f1": F1_BROKEN, "quality_delta": 0.20, "usage": "active"},
            "audit_history": [],
        }
        actions = decide(skill)
        # At exactly 0.50, it should NOT trigger (< 0.50 is the condition)
        action_types = [a["action"] for a in actions]
        assert "FIX_DESCRIPTION" not in action_types

    def test_f1_just_below_broken_threshold(self):
        from churn_decision import decide, F1_BROKEN
        skill = {
            "name": "edge", "phase": "DEPLOYED",
            "test_results": {"trigger_f1": F1_BROKEN - 0.01, "quality_delta": 0.20, "usage": "active"},
            "audit_history": [],
        }
        actions = decide(skill)
        action_types = [a["action"] for a in actions]
        assert "FIX_DESCRIPTION" in action_types

    def test_quality_exactly_at_min_threshold(self):
        from churn_decision import decide, QUALITY_DELTA_MIN
        skill = {
            "name": "edge", "phase": "DEPLOYED",
            "test_results": {"trigger_f1": 0.90, "quality_delta": QUALITY_DELTA_MIN, "usage": "active"},
            "audit_history": [],
        }
        actions = decide(skill)
        # At exactly 0.05, should NOT trigger (< 0.05 is condition)
        action_types = [a["action"] for a in actions]
        assert "REWRITE_OR_REMOVE" not in action_types

    def test_quality_just_below_min_threshold(self):
        from churn_decision import decide, QUALITY_DELTA_MIN
        skill = {
            "name": "edge", "phase": "DEPLOYED",
            "test_results": {"trigger_f1": 0.90, "quality_delta": QUALITY_DELTA_MIN - 0.01, "usage": "active"},
            "audit_history": [],
        }
        actions = decide(skill)
        action_types = [a["action"] for a in actions]
        assert "REWRITE_OR_REMOVE" in action_types


# ===========================================================================
# aggregate_benchmark — calculate_stats edge cases
# ===========================================================================
class TestCalculateStatsUnit:
    def test_two_values_stddev(self):
        from aggregate_benchmark import calculate_stats
        stats = calculate_stats([0.0, 10.0])
        # mean=5, sample variance = ((0-5)^2 + (10-5)^2) / 1 = 50, stddev = sqrt(50)
        expected_stddev = math.sqrt(50)
        assert abs(stats["stddev"] - expected_stddev) < 0.001

    def test_negative_values(self):
        from aggregate_benchmark import calculate_stats
        stats = calculate_stats([-5.0, -3.0, -1.0])
        assert stats["mean"] == -3.0
        assert stats["min"] == -5.0
        assert stats["max"] == -1.0

    def test_large_list(self):
        from aggregate_benchmark import calculate_stats
        values = list(range(1000))
        stats = calculate_stats([float(v) for v in values])
        assert abs(stats["mean"] - 499.5) < 0.01
        assert stats["min"] == 0.0
        assert stats["max"] == 999.0


# ===========================================================================
# utils — parse_skill_md edge cases
# ===========================================================================
class TestParseSkillMdUnit:
    def test_description_with_chomp_indicator(self, tmp_path):
        d = tmp_path / "chomp"
        d.mkdir()
        (d / "SKILL.md").write_text("---\nname: chomp\ndescription: >-\n  trimmed line\n---\nBody\n")
        from utils import parse_skill_md
        _, desc, _ = parse_skill_md(d)
        assert "trimmed line" in desc

    def test_empty_name(self, tmp_path):
        d = tmp_path / "empty-name"
        d.mkdir()
        (d / "SKILL.md").write_text("---\nname:\ndescription: has desc\n---\nBody\n")
        from utils import parse_skill_md
        name, desc, _ = parse_skill_md(d)
        assert name == ""
        assert desc == "has desc"

    def test_extra_frontmatter_fields_preserved(self, tmp_path):
        d = tmp_path / "extra"
        d.mkdir()
        (d / "SKILL.md").write_text("---\nname: extra\ndescription: desc\nallowed-tools: Read, Bash\n---\nBody\n")
        from utils import parse_skill_md
        name, desc, content = parse_skill_md(d)
        assert name == "extra"
        assert "allowed-tools" in content


# ===========================================================================
# history_analyzer — regex pattern correctness
# ===========================================================================
class TestHistoryAnalyzerPatterns:
    def test_skill_name_pattern_matches_slash_prefix(self):
        import history_analyzer as ha
        patterns = {}
        patterns["test-skill"] = re.compile(rf"(?:^|[\s/])(?:{re.escape('test-skill')})\b", re.IGNORECASE)
        assert patterns["test-skill"].search("/test-skill do something")

    def test_skill_name_pattern_matches_space_prefix(self):
        import history_analyzer as ha
        pattern = re.compile(rf"(?:^|[\s/])(?:{re.escape('test-skill')})\b", re.IGNORECASE)
        assert pattern.search("run test-skill now")

    def test_skill_name_pattern_matches_start_of_line(self):
        pattern = re.compile(rf"(?:^|[\s/])(?:{re.escape('test-skill')})\b", re.IGNORECASE)
        assert pattern.search("test-skill is great")

    def test_skill_name_pattern_case_insensitive(self):
        pattern = re.compile(rf"(?:^|[\s/])(?:{re.escape('test-skill')})\b", re.IGNORECASE)
        assert pattern.search("TEST-SKILL works")

    def test_skill_name_pattern_no_partial_match(self):
        pattern = re.compile(rf"(?:^|[\s/])(?:{re.escape('test')})\b", re.IGNORECASE)
        # Should NOT match "testing" because of word boundary
        assert pattern.search("testing stuff") is None
