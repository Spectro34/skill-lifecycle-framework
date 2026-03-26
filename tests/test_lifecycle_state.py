"""Functional tests for lifecycle_state.py — the state machine."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Import the module under test
import lifecycle_state as ls


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_state(skills=None, phase="IDLE"):
    """Build a minimal state dict."""
    state = ls.default_state()
    state["current_phase"] = phase
    if skills:
        state["skills_in_flight"] = skills
    return state


def make_skill(name, phase="RECOMMENDED", **overrides):
    """Build a minimal skill entry."""
    skill = {
        "name": name,
        "phase": phase,
        "recommended_at": ls.now_iso(),
        "build_started_at": None,
        "deployed_at": None,
        "last_audit": None,
        "test_results": {},
        "audit_history": [],
    }
    skill.update(overrides)
    return skill


class FakeArgs:
    """Lightweight namespace to mimic argparse output."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


# ===========================================================================
# Test: default_state
# ===========================================================================
class TestDefaultState:
    def test_has_required_keys(self):
        state = ls.default_state()
        assert state["version"] == 1
        assert state["current_phase"] == "IDLE"
        assert isinstance(state["skills_in_flight"], list)
        assert isinstance(state["history"], list)
        assert state["research_output"] is None

    def test_last_run_is_iso(self):
        state = ls.default_state()
        # Should be parseable as ISO datetime
        from datetime import datetime
        datetime.fromisoformat(state["last_run"])


# ===========================================================================
# Test: load_state / save_state (file I/O)
# ===========================================================================
class TestPersistence:
    def test_save_and_load_roundtrip(self, state_file, monkeypatch):
        monkeypatch.setattr(ls, "STATE_PATH", state_file)
        state = make_state()
        state["skills_in_flight"].append(make_skill("my-skill"))
        ls.save_state(state)

        loaded = ls.load_state()
        assert loaded["version"] == 1
        assert len(loaded["skills_in_flight"]) == 1
        assert loaded["skills_in_flight"][0]["name"] == "my-skill"

    def test_load_missing_file_returns_default(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ls, "STATE_PATH", tmp_path / "nonexistent.json")
        state = ls.load_state()
        assert state["current_phase"] == "IDLE"
        assert state["skills_in_flight"] == []

    def test_save_creates_parent_dirs(self, tmp_path, monkeypatch):
        nested = tmp_path / "deep" / "nested" / "state.json"
        monkeypatch.setattr(ls, "STATE_PATH", nested)
        ls.save_state(make_state())
        assert nested.exists()

    def test_save_updates_last_run(self, state_file, monkeypatch):
        monkeypatch.setattr(ls, "STATE_PATH", state_file)
        state = make_state()
        state["last_run"] = "2000-01-01T00:00:00+00:00"
        ls.save_state(state)
        loaded = ls.load_state()
        assert loaded["last_run"] != "2000-01-01T00:00:00+00:00"
        # Verify it's a valid recent ISO timestamp, not garbage
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(loaded["last_run"])
        assert dt.year >= 2025


# ===========================================================================
# Test: find_skill
# ===========================================================================
class TestFindSkill:
    def test_find_existing(self):
        state = make_state(skills=[make_skill("foo"), make_skill("bar")])
        assert ls.find_skill(state, "bar")["name"] == "bar"

    def test_find_missing_returns_none(self):
        state = make_state(skills=[make_skill("foo")])
        assert ls.find_skill(state, "nope") is None

    def test_find_in_empty_list(self):
        state = make_state(skills=[])
        assert ls.find_skill(state, "anything") is None


# ===========================================================================
# Test: cmd_add
# ===========================================================================
class TestCmdAdd:
    def test_add_new_skill(self, state_file, monkeypatch):
        monkeypatch.setattr(ls, "STATE_PATH", state_file)
        state = make_state()
        args = FakeArgs(name="new-skill", phase="RECOMMENDED", data=None)
        rc = ls.cmd_add(state, args)
        assert rc == 0
        assert len(state["skills_in_flight"]) == 1
        assert state["skills_in_flight"][0]["name"] == "new-skill"
        assert state["skills_in_flight"][0]["phase"] == "RECOMMENDED"

    def test_add_duplicate_fails(self, state_file, monkeypatch):
        monkeypatch.setattr(ls, "STATE_PATH", state_file)
        state = make_state(skills=[make_skill("dup")])
        args = FakeArgs(name="dup", phase="RECOMMENDED", data=None)
        rc = ls.cmd_add(state, args)
        assert rc == 1

    def test_add_invalid_phase_fails(self, state_file, monkeypatch):
        monkeypatch.setattr(ls, "STATE_PATH", state_file)
        state = make_state()
        args = FakeArgs(name="new", phase="INVALID", data=None)
        rc = ls.cmd_add(state, args)
        assert rc == 1

    def test_add_with_extra_data(self, state_file, monkeypatch):
        monkeypatch.setattr(ls, "STATE_PATH", state_file)
        state = make_state()
        args = FakeArgs(name="extra", phase="RECOMMENDED", data='{"priority": "high"}')
        rc = ls.cmd_add(state, args)
        assert rc == 0
        assert state["skills_in_flight"][0]["priority"] == "high"


# ===========================================================================
# Test: cmd_transition (state machine rules)
# ===========================================================================
class TestCmdTransition:
    @pytest.mark.parametrize("from_phase,to_phase", [
        ("RECOMMENDED", "BUILDING"),
        ("BUILDING", "TESTING"),
        ("TESTING", "DEPLOYED"),
        ("TESTING", "BUILDING"),  # retry
        ("DEPLOYED", "MONITORING"),
        ("MONITORING", "REBUILDING"),
        ("MONITORING", "CHURNED"),
        ("REBUILDING", "TESTING"),
    ])
    def test_valid_transitions(self, from_phase, to_phase, state_file, monkeypatch):
        monkeypatch.setattr(ls, "STATE_PATH", state_file)
        state = make_state(skills=[make_skill("s", phase=from_phase)])
        args = FakeArgs(name="s", to=to_phase)
        rc = ls.cmd_transition(state, args)
        assert rc == 0
        assert state["skills_in_flight"][0]["phase"] == to_phase

    @pytest.mark.parametrize("from_phase,to_phase", [
        ("RECOMMENDED", "TESTING"),       # skip BUILDING
        ("RECOMMENDED", "DEPLOYED"),      # skip ahead
        ("BUILDING", "DEPLOYED"),         # skip TESTING
        ("DEPLOYED", "BUILDING"),         # backward
        ("CHURNED", "RECOMMENDED"),       # terminal
        ("CHURNED", "BUILDING"),          # terminal
        ("MONITORING", "DEPLOYED"),       # wrong direction
    ])
    def test_invalid_transitions(self, from_phase, to_phase, state_file, monkeypatch):
        monkeypatch.setattr(ls, "STATE_PATH", state_file)
        state = make_state(skills=[make_skill("s", phase=from_phase)])
        args = FakeArgs(name="s", to=to_phase)
        rc = ls.cmd_transition(state, args)
        assert rc == 1
        # Phase should NOT change
        assert state["skills_in_flight"][0]["phase"] == from_phase

    def test_transition_records_history(self, state_file, monkeypatch):
        monkeypatch.setattr(ls, "STATE_PATH", state_file)
        state = make_state(skills=[make_skill("s", phase="RECOMMENDED")])
        args = FakeArgs(name="s", to="BUILDING")
        ls.cmd_transition(state, args)
        assert len(state["history"]) == 1
        assert state["history"][0]["from"] == "RECOMMENDED"
        assert state["history"][0]["to"] == "BUILDING"

    def test_transition_sets_timestamps(self, state_file, monkeypatch):
        monkeypatch.setattr(ls, "STATE_PATH", state_file)

        # BUILDING sets build_started_at
        state = make_state(skills=[make_skill("s", phase="RECOMMENDED")])
        ls.cmd_transition(state, FakeArgs(name="s", to="BUILDING"))
        ts = state["skills_in_flight"][0]["build_started_at"]
        assert isinstance(ts, str)
        from datetime import datetime
        datetime.fromisoformat(ts)  # Must be valid ISO timestamp

    def test_transition_deployed_sets_timestamp(self, state_file, monkeypatch):
        monkeypatch.setattr(ls, "STATE_PATH", state_file)
        state = make_state(skills=[make_skill("s", phase="TESTING")])
        ls.cmd_transition(state, FakeArgs(name="s", to="DEPLOYED"))
        ts = state["skills_in_flight"][0]["deployed_at"]
        assert isinstance(ts, str)
        from datetime import datetime
        datetime.fromisoformat(ts)  # Must be valid ISO timestamp

    def test_transition_nonexistent_skill_fails(self, state_file, monkeypatch):
        monkeypatch.setattr(ls, "STATE_PATH", state_file)
        state = make_state()
        args = FakeArgs(name="ghost", to="BUILDING")
        rc = ls.cmd_transition(state, args)
        assert rc == 1


# ===========================================================================
# Test: cmd_list
# ===========================================================================
class TestCmdList:
    def test_list_matching_phase(self, capsys):
        state = make_state(skills=[
            make_skill("deploy-helper", phase="RECOMMENDED"),
            make_skill("test-runner", phase="BUILDING"),
            make_skill("lint-checker", phase="RECOMMENDED"),
        ])
        ls.cmd_list(state, FakeArgs(phase="RECOMMENDED"))
        out = capsys.readouterr().out
        assert "deploy-helper" in out
        assert "lint-checker" in out
        assert "test-runner" not in out

    def test_list_empty_phase(self, capsys):
        state = make_state(skills=[make_skill("some-skill", phase="BUILDING")])
        ls.cmd_list(state, FakeArgs(phase="DEPLOYED"))
        out = capsys.readouterr().out
        assert "No skills" in out


# ===========================================================================
# Test: cmd_update_audit
# ===========================================================================
class TestCmdUpdateAudit:
    def test_update_audit_records_data(self, state_file, monkeypatch):
        monkeypatch.setattr(ls, "STATE_PATH", state_file)
        state = make_state(skills=[make_skill("s")])
        args = FakeArgs(name="s", f1=0.85, quality_delta=0.22, usage="active")
        rc = ls.cmd_update_audit(state, args)
        assert rc == 0
        skill = state["skills_in_flight"][0]
        assert skill["test_results"]["trigger_f1"] == 0.85
        assert skill["test_results"]["quality_delta"] == 0.22
        assert skill["test_results"]["usage"] == "active"
        assert len(skill["audit_history"]) == 1

    def test_update_audit_appends_history(self, state_file, monkeypatch):
        monkeypatch.setattr(ls, "STATE_PATH", state_file)
        state = make_state(skills=[make_skill("s")])
        for f1 in [0.70, 0.75, 0.80]:
            ls.cmd_update_audit(state, FakeArgs(name="s", f1=f1, quality_delta=0.10, usage="active"))
        assert len(state["skills_in_flight"][0]["audit_history"]) == 3

    def test_update_audit_missing_skill(self, state_file, monkeypatch):
        monkeypatch.setattr(ls, "STATE_PATH", state_file)
        state = make_state()
        args = FakeArgs(name="ghost", f1=0.5, quality_delta=0.1, usage="never")
        rc = ls.cmd_update_audit(state, args)
        assert rc == 1


# ===========================================================================
# Test: cmd_mark_churned
# ===========================================================================
class TestCmdMarkChurned:
    def test_mark_churned_sets_fields(self, state_file, monkeypatch):
        monkeypatch.setattr(ls, "STATE_PATH", state_file)
        state = make_state(skills=[make_skill("s", phase="MONITORING")])
        args = FakeArgs(name="s", reason="never used")
        rc = ls.cmd_mark_churned(state, args)
        assert rc == 0
        skill = state["skills_in_flight"][0]
        assert skill["phase"] == "CHURNED"
        assert skill["churn_reason"] == "never used"
        assert skill["churned_at"] is not None

    def test_mark_churned_records_history(self, state_file, monkeypatch):
        monkeypatch.setattr(ls, "STATE_PATH", state_file)
        state = make_state(skills=[make_skill("s", phase="MONITORING")])
        ls.cmd_mark_churned(state, FakeArgs(name="s", reason="low quality"))
        assert len(state["history"]) == 1
        entry = state["history"][0]
        assert entry["to"] == "CHURNED"
        assert entry["reason"] == "low quality"
        # Critical: 'from' must record the ORIGINAL phase, not the new one
        assert entry["from"] == "MONITORING"
        assert entry["from"] != "CHURNED"  # Explicit guard against the old bug


# ===========================================================================
# Test: CLI integration (subprocess)
# ===========================================================================
class TestCLI:
    SCRIPT = str(Path(__file__).resolve().parent.parent / ".claude" / "skills" / "skill-lifecycle" / "scripts" / "lifecycle_state.py")

    def _run(self, args, cwd, home):
        """Run the CLI in a sandbox: cwd and HOME both point to temp dirs."""
        env = dict(os.environ)
        env["HOME"] = str(home)  # Prevent fallback to real ~/.claude/
        cmd = [sys.executable, self.SCRIPT] + args
        return subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd), env=env)

    def test_status_no_state_file(self, tmp_path):
        """status should work even with no existing state (creates default)."""
        # No .claude dir exists in tmp_path, so script falls back to HOME/.claude
        # HOME is sandboxed to tmp_path, so no real files are touched.
        result = self._run(["status"], cwd=tmp_path, home=tmp_path)
        assert result.returncode == 0
        assert "State file" in result.stdout

    def test_add_and_list_via_cli(self, tmp_path):
        """Add a skill via CLI and verify it appears in list."""
        # Create .claude dir inside tmp_path so STATE_PATH resolves to project-scoped
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        result = self._run(["add", "--name", "cli-test", "--phase", "RECOMMENDED"], cwd=tmp_path, home=tmp_path)
        assert result.returncode == 0, f"stderr: {result.stderr}"

        result = self._run(["list", "--phase", "RECOMMENDED"], cwd=tmp_path, home=tmp_path)
        assert "cli-test" in result.stdout
