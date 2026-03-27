#!/usr/bin/env python3
"""Integration tests for the skill lifecycle framework.

Tests all four Python scripts: lifecycle_state, gap_analysis, churn_decision, history_analyzer.
Run: python3 -m pytest tests/test_lifecycle.py -v
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parent.parent / ".claude" / "skills" / "skill-lifecycle" / "scripts"


def run_script(name, args, stdin_data=None):
    """Run a lifecycle script and return (stdout, stderr, returncode)."""
    cmd = [sys.executable, str(SCRIPTS / name)] + args
    result = subprocess.run(cmd, capture_output=True, text=True, input=stdin_data)
    return result.stdout, result.stderr, result.returncode


class TestLifecycleState:
    """Test lifecycle_state.py state machine."""

    @pytest.fixture(autouse=True)
    def setup_state(self, tmp_path, monkeypatch):
        """Use a temp state file for each test."""
        self.state_file = tmp_path / "state.json"
        # Patch the script to use our temp file by running from tmp_path
        # which has .claude/ dir
        self.claude_dir = tmp_path / ".claude"
        self.claude_dir.mkdir()
        monkeypatch.chdir(tmp_path)

    def run(self, args, stdin_data=None):
        return run_script("lifecycle_state.py", args, stdin_data)

    def test_status_empty(self):
        out, err, rc = self.run(["status"])
        assert rc == 0
        assert "Skills tracked: 0" in out

    def test_add_skill(self):
        out, err, rc = self.run(["add", "--name", "test-skill", "--phase", "RECOMMENDED"])
        assert rc == 0
        assert "Added" in out

    def test_add_duplicate_fails(self):
        self.run(["add", "--name", "dupe", "--phase", "RECOMMENDED"])
        out, err, rc = self.run(["add", "--name", "dupe", "--phase", "RECOMMENDED"])
        assert rc == 1
        assert "already tracked" in err

    def test_add_invalid_phase_fails(self):
        out, err, rc = self.run(["add", "--name", "bad", "--phase", "INVALID"])
        assert rc == 1
        assert "invalid phase" in err.lower()

    def test_transition_valid(self):
        self.run(["add", "--name", "t", "--phase", "RECOMMENDED"])
        out, err, rc = self.run(["transition", "--name", "t", "--to", "BUILDING"])
        assert rc == 0
        assert "RECOMMENDED → BUILDING" in out

    def test_transition_invalid(self):
        self.run(["add", "--name", "t", "--phase", "RECOMMENDED"])
        out, err, rc = self.run(["transition", "--name", "t", "--to", "DEPLOYED"])
        assert rc == 1
        assert "cannot transition" in err.lower()

    def test_transition_nonexistent(self):
        out, err, rc = self.run(["transition", "--name", "ghost", "--to", "BUILDING"])
        assert rc == 1
        assert "not found" in err.lower()

    def test_full_lifecycle(self):
        """Test complete happy path: RECOMMENDED → BUILDING → TESTING → DEPLOYED → MONITORING."""
        self.run(["add", "--name", "s", "--phase", "RECOMMENDED"])
        self.run(["transition", "--name", "s", "--to", "BUILDING"])
        self.run(["transition", "--name", "s", "--to", "TESTING"])
        self.run(["transition", "--name", "s", "--to", "DEPLOYED"])
        out, err, rc = self.run(["transition", "--name", "s", "--to", "MONITORING"])
        assert rc == 0
        assert "DEPLOYED → MONITORING" in out

    def test_churned_is_terminal(self):
        self.run(["add", "--name", "s", "--phase", "RECOMMENDED"])
        self.run(["transition", "--name", "s", "--to", "BUILDING"])
        self.run(["transition", "--name", "s", "--to", "TESTING"])
        self.run(["transition", "--name", "s", "--to", "DEPLOYED"])
        self.run(["transition", "--name", "s", "--to", "MONITORING"])
        self.run(["mark-churned", "--name", "s", "--reason", "bad"])
        out, err, rc = self.run(["transition", "--name", "s", "--to", "REBUILDING"])
        assert rc == 1  # CHURNED is terminal

    def test_rebuilding_path(self):
        """Test MONITORING → REBUILDING → TESTING path."""
        self.run(["add", "--name", "s", "--phase", "RECOMMENDED"])
        self.run(["transition", "--name", "s", "--to", "BUILDING"])
        self.run(["transition", "--name", "s", "--to", "TESTING"])
        self.run(["transition", "--name", "s", "--to", "DEPLOYED"])
        self.run(["transition", "--name", "s", "--to", "MONITORING"])
        self.run(["transition", "--name", "s", "--to", "REBUILDING"])
        out, err, rc = self.run(["transition", "--name", "s", "--to", "TESTING"])
        assert rc == 0

    def test_list_phase(self):
        self.run(["add", "--name", "a", "--phase", "RECOMMENDED"])
        self.run(["add", "--name", "b", "--phase", "RECOMMENDED"])
        self.run(["transition", "--name", "a", "--to", "BUILDING"])
        out, err, rc = self.run(["list", "--phase", "RECOMMENDED"])
        assert "b" in out
        assert "a" not in out

    def test_update_audit(self):
        self.run(["add", "--name", "s", "--phase", "RECOMMENDED"])
        self.run(["transition", "--name", "s", "--to", "BUILDING"])
        self.run(["transition", "--name", "s", "--to", "TESTING"])
        self.run(["transition", "--name", "s", "--to", "DEPLOYED"])
        self.run(["transition", "--name", "s", "--to", "MONITORING"])
        out, err, rc = self.run(["update-audit", "--name", "s", "--f1", "0.85", "--quality-delta", "0.22", "--usage", "active"])
        assert rc == 0
        assert "F1=0.85" in out

    def test_mark_churned(self):
        self.run(["add", "--name", "s", "--phase", "RECOMMENDED"])
        self.run(["transition", "--name", "s", "--to", "BUILDING"])
        self.run(["transition", "--name", "s", "--to", "TESTING"])
        self.run(["transition", "--name", "s", "--to", "DEPLOYED"])
        self.run(["transition", "--name", "s", "--to", "MONITORING"])
        out, err, rc = self.run(["mark-churned", "--name", "s", "--reason", "never used"])
        assert rc == 0
        assert "CHURNED" in out


class TestGapAnalysis:
    """Test gap_analysis.py recommendation cross-referencing."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.tmp = tmp_path
        # Create fake skills
        skill_dir = tmp_path / "skills" / "existing-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nname: existing-skill\ndescription: test\n---\n")
        # Create fake history
        self.history = tmp_path / "history.jsonl"
        self.history.write_text(
            '{"display": "deploy the terraform changes", "timestamp": 1711234567000, "sessionId": "s1"}\n'
            '{"display": "run the ansible playbook", "timestamp": 1711234568000, "sessionId": "s2"}\n'
            '{"display": "terraform plan review", "timestamp": 1711234569000, "sessionId": "s3"}\n'
        )

    def test_gap_deduplication(self):
        """Already-installed skills should be in already_covered, not gaps."""
        recs = json.dumps([
            {"name": "existing-skill", "priority": "High", "type": "test", "why": "test", "steps": "test", "tools": "test"},
            {"name": "new-skill", "priority": "High", "type": "test", "why": "test", "steps": "test", "tools": "test"},
        ])
        out, err, rc = run_script("gap_analysis.py", [
            "--skills-dirs", str(self.tmp / "skills"),
            "--plugins-dir", str(self.tmp / "noplugins"),
            "--history", str(self.history),
        ], stdin_data=recs)
        assert rc == 0
        result = json.loads(out)
        assert result["total_gaps"] == 1
        assert result["total_covered"] == 1
        assert result["gaps"][0]["name"] == "new-skill"
        assert result["already_covered"][0]["name"] == "existing-skill"

    def test_activity_match_scoring(self):
        """Skills matching user history keywords should get higher activity scores."""
        recs = json.dumps([
            {"name": "terraform-review", "priority": "Medium", "type": "test", "why": "terraform plan changes", "steps": "review terraform", "tools": "terraform"},
            {"name": "unrelated-thing", "priority": "High", "type": "test", "why": "something else entirely", "steps": "do stuff", "tools": "whatever"},
        ])
        out, err, rc = run_script("gap_analysis.py", [
            "--skills-dirs", str(self.tmp / "skills"),
            "--plugins-dir", str(self.tmp / "noplugins"),
            "--history", str(self.history),
        ], stdin_data=recs)
        result = json.loads(out)
        terraform_score = next(g for g in result["gaps"] if g["name"] == "terraform-review")["activity_match_score"]
        unrelated_score = next(g for g in result["gaps"] if g["name"] == "unrelated-thing")["activity_match_score"]
        assert terraform_score > unrelated_score

    def test_empty_recommendations(self):
        out, err, rc = run_script("gap_analysis.py", [
            "--skills-dirs", str(self.tmp / "skills"),
            "--plugins-dir", str(self.tmp / "noplugins"),
            "--history", str(self.history),
        ], stdin_data="[]")
        result = json.loads(out)
        assert result["total_gaps"] == 0

    def test_no_history_file(self):
        """Should work even if history.jsonl doesn't exist."""
        recs = json.dumps([{"name": "s", "priority": "High", "type": "t", "why": "w", "steps": "s", "tools": "t"}])
        out, err, rc = run_script("gap_analysis.py", [
            "--skills-dirs", str(self.tmp / "skills"),
            "--plugins-dir", str(self.tmp / "noplugins"),
            "--history", str(self.tmp / "nonexistent.jsonl"),
        ], stdin_data=recs)
        assert rc == 0
        result = json.loads(out)
        assert result["total_gaps"] == 1


class TestChurnDecision:
    """Test churn_decision.py decision engine."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.state_file = tmp_path / "state.json"

    def write_state(self, skills):
        state = {"version": 1, "last_run": "2026-03-26T10:00:00Z", "current_phase": "IDLE",
                 "project": "/test", "skills_in_flight": skills, "history": []}
        self.state_file.write_text(json.dumps(state))

    def run_churn(self):
        out, err, rc = run_script("churn_decision.py", ["--state", str(self.state_file)])
        return json.loads(out) if rc == 0 else None, rc

    def test_healthy_skill_no_action(self):
        self.write_state([{
            "name": "good-skill", "phase": "MONITORING",
            "test_results": {"trigger_f1": 0.92, "quality_delta": 0.25, "usage": "active"},
            "audit_history": [], "last_audit": "2026-03-25T10:00:00Z", "deployed_at": "2026-03-01T10:00:00Z",
        }])
        result, rc = self.run_churn()
        assert rc == 0
        assert result["total_actions"] == 0

    def test_broken_trigger_flagged(self):
        self.write_state([{
            "name": "broken", "phase": "DEPLOYED",
            "test_results": {"trigger_f1": 0.35, "quality_delta": 0.20, "usage": "active"},
            "audit_history": [], "last_audit": "2026-03-25T10:00:00Z", "deployed_at": "2026-03-01T10:00:00Z",
        }])
        result, rc = self.run_churn()
        assert result["total_actions"] == 1
        assert result["actions"][0]["action"] == "FIX_DESCRIPTION"

    def test_low_quality_flagged(self):
        self.write_state([{
            "name": "useless", "phase": "MONITORING",
            "test_results": {"trigger_f1": 0.85, "quality_delta": 0.03, "usage": "active"},
            "audit_history": [], "last_audit": "2026-03-25T10:00:00Z", "deployed_at": "2026-03-01T10:00:00Z",
        }])
        result, rc = self.run_churn()
        assert result["actions"][0]["action"] == "REWRITE_OR_REMOVE"

    def test_dormant_flagged(self):
        self.write_state([{
            "name": "abandoned", "phase": "DEPLOYED",
            "test_results": {"trigger_f1": 0.80, "quality_delta": 0.15, "usage": "dormant"},
            "audit_history": [], "last_audit": "2026-03-25T10:00:00Z", "deployed_at": "2026-01-01T10:00:00Z",
        }])
        result, rc = self.run_churn()
        assert result["total_actions"] == 1
        assert result["actions"][0]["action"] == "REVIEW_FOR_REMOVAL"

    def test_never_used_flagged(self):
        self.write_state([{
            "name": "ghost", "phase": "MONITORING",
            "test_results": {"trigger_f1": 0.70, "quality_delta": 0.10, "usage": "never"},
            "audit_history": [], "last_audit": "2026-03-25T10:00:00Z", "deployed_at": "2026-03-01T10:00:00Z",
        }])
        result, rc = self.run_churn()
        assert any(a["action"] == "REVIEW_FOR_REMOVAL" for a in result["actions"])

    def test_declining_f1_flagged(self):
        self.write_state([{
            "name": "declining", "phase": "MONITORING",
            "test_results": {"trigger_f1": 0.55, "quality_delta": 0.15, "usage": "active"},
            "audit_history": [
                {"trigger_f1": 0.90, "timestamp": "2026-01-01T10:00:00Z"},
                {"trigger_f1": 0.80, "timestamp": "2026-02-01T10:00:00Z"},
                {"trigger_f1": 0.55, "timestamp": "2026-03-01T10:00:00Z"},
            ],
            "last_audit": "2026-03-25T10:00:00Z", "deployed_at": "2026-01-01T10:00:00Z",
        }])
        result, rc = self.run_churn()
        assert any(a["action"] == "INVESTIGATE" for a in result["actions"])

    def test_multiple_issues_picks_most_severe(self):
        """If a skill has both low F1 AND low quality, pick the most severe action."""
        self.write_state([{
            "name": "total-mess", "phase": "MONITORING",
            "test_results": {"trigger_f1": 0.30, "quality_delta": 0.02, "usage": "dormant"},
            "audit_history": [], "last_audit": "2026-03-25T10:00:00Z", "deployed_at": "2026-01-01T10:00:00Z",
        }])
        result, rc = self.run_churn()
        # Should deduplicate: only one action per skill (most severe)
        actions_for_skill = [a for a in result["actions"] if a["skill"] == "total-mess"]
        assert len(actions_for_skill) == 1
        assert actions_for_skill[0]["action"] == "REWRITE_OR_REMOVE"

    def test_building_skills_ignored(self):
        """Skills still being built shouldn't be evaluated for churn."""
        self.write_state([{
            "name": "wip", "phase": "BUILDING",
            "test_results": {}, "audit_history": [],
            "last_audit": None, "deployed_at": None,
        }])
        result, rc = self.run_churn()
        assert result["total_skills_evaluated"] == 0

    def test_quality_delta_percentage_string(self):
        """Should handle quality_delta as string like '+22%'."""
        self.write_state([{
            "name": "pct-test", "phase": "DEPLOYED",
            "test_results": {"trigger_f1": 0.85, "quality_delta": "+3%", "usage": "active"},
            "audit_history": [], "last_audit": "2026-03-25T10:00:00Z", "deployed_at": "2026-03-01T10:00:00Z",
        }])
        result, rc = self.run_churn()
        assert result["total_actions"] == 1
        assert result["actions"][0]["action"] == "REWRITE_OR_REMOVE"

    def test_no_state_file(self):
        out, err, rc = run_script("churn_decision.py", ["--state", "/nonexistent/state.json"])
        assert rc == 1


class TestHistoryAnalyzer:
    """Test history_analyzer.py usage mining."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.tmp = tmp_path
        # Create skills
        for name in ["skill-a", "skill-b"]:
            d = tmp_path / "skills" / name
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: test\n---\n")

    def test_detects_invocations(self):
        import time
        now_ms = int(time.time() * 1000)
        history = self.tmp / "history.jsonl"
        history.write_text(
            f'{{"display": "/skill-a do something", "timestamp": {now_ms}, "sessionId": "s1"}}\n'
            f'{{"display": "/skill-a again", "timestamp": {now_ms + 1000}, "sessionId": "s2"}}\n'
            f'{{"display": "unrelated prompt", "timestamp": {now_ms + 2000}, "sessionId": "s3"}}\n'
        )
        out, err, rc = run_script("history_analyzer.py", [
            "--skills-dir", str(self.tmp / "skills"),
            "--history", str(history),
        ])
        result = json.loads(out)
        skill_a = next(s for s in result["skills"] if s["name"] == "skill-a")
        skill_b = next(s for s in result["skills"] if s["name"] == "skill-b")
        assert skill_a["invocations"] == 2
        assert skill_a["status"] == "active"
        assert skill_b["invocations"] == 0
        assert skill_b["status"] == "never"

    def test_no_history(self):
        """When history file doesn't exist, all skills show as never used."""
        # Create an empty history file (no entries)
        empty_history = self.tmp / "empty.jsonl"
        empty_history.write_text("")
        out, err, rc = run_script("history_analyzer.py", [
            "--skills-dir", str(self.tmp / "skills"),
            "--history", str(empty_history),
        ])
        result = json.loads(out)
        assert result["active"] == 0
        assert result["never_used"] == 2

    def test_no_skills(self):
        out, err, rc = run_script("history_analyzer.py", [
            "--skills-dir", str(self.tmp / "empty"),
            "--history", str(self.tmp / "h.jsonl"),
        ])
        assert rc == 1
