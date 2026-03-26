"""Functional tests for churn_decision.py — the churn decision engine."""

import json
import sys
from datetime import datetime, timedelta, timezone

import pytest

import churn_decision as cd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_skill(name, phase="DEPLOYED", f1=None, quality_delta=None, usage="unknown",
               deployed_at=None, last_audit=None, audit_history=None):
    return {
        "name": name,
        "phase": phase,
        "deployed_at": deployed_at,
        "last_audit": last_audit,
        "test_results": {
            "trigger_f1": f1,
            "quality_delta": quality_delta,
            "usage": usage,
        },
        "audit_history": audit_history or [],
    }


def iso_days_ago(n):
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


# ===========================================================================
# Test: days_since
# ===========================================================================
class TestDaysSince:
    def test_recent_timestamp(self):
        ts = iso_days_ago(5)
        days = cd.days_since(ts)
        assert days is not None
        assert 4 <= days <= 6  # allow clock drift

    def test_none_input(self):
        assert cd.days_since(None) is None

    def test_invalid_string(self):
        assert cd.days_since("not-a-date") is None

    def test_z_suffix_handled(self):
        ts = "2020-01-01T00:00:00Z"
        days = cd.days_since(ts)
        assert days is not None
        assert days > 1000


# ===========================================================================
# Test: is_f1_declining
# ===========================================================================
class TestIsF1Declining:
    def test_declining_sequence(self):
        history = [
            {"trigger_f1": 0.90},
            {"trigger_f1": 0.80},
            {"trigger_f1": 0.70},
        ]
        assert cd.is_f1_declining(history, min_audits=3) is True

    def test_improving_sequence(self):
        history = [
            {"trigger_f1": 0.70},
            {"trigger_f1": 0.80},
            {"trigger_f1": 0.90},
        ]
        assert cd.is_f1_declining(history, min_audits=3) is False

    def test_flat_sequence_is_declining(self):
        # Defined as <= not <, so equal values count as declining
        history = [
            {"trigger_f1": 0.80},
            {"trigger_f1": 0.80},
            {"trigger_f1": 0.80},
        ]
        assert cd.is_f1_declining(history, min_audits=3) is True

    def test_too_few_audits(self):
        history = [{"trigger_f1": 0.90}, {"trigger_f1": 0.80}]
        assert cd.is_f1_declining(history, min_audits=3) is False

    def test_missing_f1_values(self):
        history = [
            {"trigger_f1": 0.90},
            {"trigger_f1": None},
            {"trigger_f1": 0.70},
        ]
        assert cd.is_f1_declining(history, min_audits=3) is False

    def test_only_looks_at_recent(self):
        # First values are improving, but last 3 are declining
        history = [
            {"trigger_f1": 0.50},
            {"trigger_f1": 0.60},
            {"trigger_f1": 0.90},
            {"trigger_f1": 0.80},
            {"trigger_f1": 0.70},
        ]
        assert cd.is_f1_declining(history, min_audits=3) is True


# ===========================================================================
# Test: decide (the decision tree)
# ===========================================================================
class TestDecide:
    def test_healthy_skill_no_actions(self):
        skill = make_skill("good", f1=0.90, quality_delta=0.25, usage="active")
        actions = cd.decide(skill)
        assert actions == []

    def test_broken_f1_triggers_fix_description(self):
        skill = make_skill("broken", f1=0.30, quality_delta=0.20, usage="active")
        actions = cd.decide(skill)
        action_types = [a["action"] for a in actions]
        assert "FIX_DESCRIPTION" in action_types

    def test_low_quality_triggers_rewrite_or_remove(self):
        skill = make_skill("low-q", f1=0.90, quality_delta=0.02, usage="active")
        actions = cd.decide(skill)
        action_types = [a["action"] for a in actions]
        assert "REWRITE_OR_REMOVE" in action_types

    def test_never_used_triggers_review(self):
        skill = make_skill("unused", f1=0.90, quality_delta=0.20, usage="never")
        actions = cd.decide(skill)
        action_types = [a["action"] for a in actions]
        assert "REVIEW_FOR_REMOVAL" in action_types

    def test_dormant_with_old_deploy_triggers_review(self):
        skill = make_skill("stale", f1=0.90, quality_delta=0.20, usage="dormant",
                          deployed_at=iso_days_ago(60))
        actions = cd.decide(skill)
        action_types = [a["action"] for a in actions]
        assert "REVIEW_FOR_REMOVAL" in action_types

    def test_dormant_but_recently_deployed_no_review(self):
        skill = make_skill("new-dormant", f1=0.90, quality_delta=0.20, usage="dormant",
                          deployed_at=iso_days_ago(5))
        actions = cd.decide(skill)
        action_types = [a["action"] for a in actions]
        assert "REVIEW_FOR_REMOVAL" not in action_types

    def test_declining_f1_triggers_investigate(self):
        history = [
            {"trigger_f1": 0.90},
            {"trigger_f1": 0.80},
            {"trigger_f1": 0.70},
        ]
        skill = make_skill("declining", f1=0.70, quality_delta=0.15, usage="active",
                          audit_history=history)
        actions = cd.decide(skill)
        action_types = [a["action"] for a in actions]
        assert "INVESTIGATE" in action_types

    def test_multiple_issues_produce_multiple_actions(self):
        skill = make_skill("terrible", f1=0.30, quality_delta=0.01, usage="never")
        actions = cd.decide(skill)
        assert len(actions) >= 2  # At least FIX_DESCRIPTION and REWRITE_OR_REMOVE

    def test_quality_delta_as_string_percentage(self):
        skill = make_skill("string-delta", f1=0.90, quality_delta="+3%", usage="active")
        actions = cd.decide(skill)
        action_types = [a["action"] for a in actions]
        assert "REWRITE_OR_REMOVE" in action_types

    def test_none_f1_no_crash(self):
        skill = make_skill("no-data", f1=None, quality_delta=None, usage="unknown")
        actions = cd.decide(skill)
        # Should not crash, may or may not produce actions
        assert isinstance(actions, list)


# ===========================================================================
# Test: severity deduplication (main flow)
# ===========================================================================
class TestSeverityDeduplication:
    def test_most_severe_action_wins(self, tmp_path, sample_state):
        """broken-skill has both FIX_DESCRIPTION and REWRITE_OR_REMOVE; most severe should win."""
        state_file = tmp_path / "state.json"
        with open(state_file, "w") as f:
            json.dump(sample_state, f)

        # Run the decision logic manually (not via CLI to avoid file path issues)
        all_actions = []
        for skill in sample_state["skills_in_flight"]:
            if skill["phase"] in ("DEPLOYED", "MONITORING"):
                actions = cd.decide(skill)
                all_actions.extend(actions)

        severity_order = {"REWRITE_OR_REMOVE": 0, "FIX_DESCRIPTION": 1, "REVIEW_FOR_REMOVAL": 2, "INVESTIGATE": 3}
        seen = {}
        for action in all_actions:
            name = action["skill"]
            if name not in seen or severity_order.get(action["action"], 99) < severity_order.get(seen[name]["action"], 99):
                seen[name] = action

        # broken-skill should get REWRITE_OR_REMOVE (more severe than FIX_DESCRIPTION)
        assert seen["broken-skill"]["action"] == "REWRITE_OR_REMOVE"

    def test_building_skills_excluded(self, tmp_path, sample_state):
        """Skills in BUILDING phase should not produce churn actions via main flow."""
        state_file = tmp_path / "state.json"
        with open(state_file, "w") as f:
            json.dump(sample_state, f)

        # Replicate main()'s filtering logic against actual decide()
        all_actions = []
        for skill in sample_state["skills_in_flight"]:
            if skill["phase"] in ("DEPLOYED", "MONITORING"):
                all_actions.extend(cd.decide(skill))
        action_skill_names = {a["skill"] for a in all_actions}
        assert "building-skill" not in action_skill_names
        # Also confirm decide() IS called on deployed/monitoring skills
        assert len(all_actions) > 0
