"""Shared fixtures for the Skill Lifecycle Framework test suite."""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path setup — allow imports from the scripts directories
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LIFECYCLE_SCRIPTS = PROJECT_ROOT / ".claude" / "skills" / "skill-lifecycle" / "scripts"
CREATOR_SCRIPTS = PROJECT_ROOT / ".claude" / "skills" / "skill-creator" / "scripts"

sys.path.insert(0, str(LIFECYCLE_SCRIPTS))
sys.path.insert(0, str(CREATOR_SCRIPTS))


# ---------------------------------------------------------------------------
# Temporary directory fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def tmp_dir(tmp_path):
    """Provide a clean temporary directory."""
    return tmp_path


@pytest.fixture
def state_file(tmp_path):
    """Provide a path for a temporary state file."""
    return tmp_path / "skill-lifecycle-state.json"


# ---------------------------------------------------------------------------
# Skill directory fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def skill_dir(tmp_path):
    """Create a minimal valid skill directory with SKILL.md."""
    skill_path = tmp_path / "test-skill"
    skill_path.mkdir()
    (skill_path / "SKILL.md").write_text(
        '---\nname: test-skill\ndescription: A test skill for validation\n---\n\nBody content here.\n'
    )
    return skill_path


@pytest.fixture
def skills_dir(tmp_path):
    """Create a skills directory with multiple skills."""
    base = tmp_path / "skills"
    base.mkdir()
    for name in ["alpha-skill", "beta-skill", "gamma-skill"]:
        d = base / name
        d.mkdir()
        (d / "SKILL.md").write_text(
            f'---\nname: {name}\ndescription: Skill {name} for testing\n---\n\nBody.\n'
        )
    return base


# ---------------------------------------------------------------------------
# History file fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def history_file(tmp_path):
    """Create a mock history.jsonl with sample entries."""
    path = tmp_path / "history.jsonl"
    entries = [
        {"display": "/alpha-skill do something", "timestamp": 1711400000000, "sessionId": "s1"},
        {"display": "run alpha-skill again", "timestamp": 1711400100000, "sessionId": "s1"},
        {"display": "/beta-skill check things", "timestamp": 1711400200000, "sessionId": "s2"},
        {"display": "unrelated conversation", "timestamp": 1711400300000, "sessionId": "s3"},
    ]
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    return path


# ---------------------------------------------------------------------------
# State fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def sample_state():
    """Return a populated state dict for testing."""
    return {
        "version": 1,
        "last_run": "2026-03-25T10:00:00+00:00",
        "current_phase": "MONITOR",
        "project": "/tmp/test-project",
        "skills_in_flight": [
            {
                "name": "healthy-skill",
                "phase": "DEPLOYED",
                "recommended_at": "2026-03-01T00:00:00+00:00",
                "build_started_at": "2026-03-02T00:00:00+00:00",
                "deployed_at": "2026-03-10T00:00:00+00:00",
                "last_audit": "2026-03-20T00:00:00+00:00",
                "test_results": {
                    "trigger_f1": 0.90,
                    "quality_delta": 0.25,
                    "usage": "active",
                },
                "audit_history": [
                    {"timestamp": "2026-03-15T00:00:00+00:00", "trigger_f1": 0.88, "quality_delta": 0.20, "usage": "active"},
                    {"timestamp": "2026-03-20T00:00:00+00:00", "trigger_f1": 0.90, "quality_delta": 0.25, "usage": "active"},
                ],
            },
            {
                "name": "broken-skill",
                "phase": "MONITORING",
                "recommended_at": "2026-03-01T00:00:00+00:00",
                "build_started_at": "2026-03-02T00:00:00+00:00",
                "deployed_at": "2026-03-05T00:00:00+00:00",
                "last_audit": "2026-03-20T00:00:00+00:00",
                "test_results": {
                    "trigger_f1": 0.35,
                    "quality_delta": 0.03,
                    "usage": "never",
                },
                "audit_history": [],
            },
            {
                "name": "declining-skill",
                "phase": "MONITORING",
                "recommended_at": "2026-03-01T00:00:00+00:00",
                "build_started_at": "2026-03-02T00:00:00+00:00",
                "deployed_at": "2026-03-05T00:00:00+00:00",
                "last_audit": "2026-03-25T00:00:00+00:00",
                "test_results": {
                    "trigger_f1": 0.60,
                    "quality_delta": 0.10,
                    "usage": "active",
                },
                "audit_history": [
                    {"timestamp": "2026-03-10T00:00:00+00:00", "trigger_f1": 0.85, "quality_delta": 0.20, "usage": "active"},
                    {"timestamp": "2026-03-15T00:00:00+00:00", "trigger_f1": 0.75, "quality_delta": 0.15, "usage": "active"},
                    {"timestamp": "2026-03-20T00:00:00+00:00", "trigger_f1": 0.65, "quality_delta": 0.12, "usage": "active"},
                ],
            },
            {
                "name": "building-skill",
                "phase": "BUILDING",
                "recommended_at": "2026-03-01T00:00:00+00:00",
                "build_started_at": "2026-03-24T00:00:00+00:00",
                "deployed_at": None,
                "last_audit": None,
                "test_results": {},
                "audit_history": [],
            },
        ],
        "installed_skills_snapshot": [],
        "research_output": None,
        "gap_analysis": None,
        "churn_candidates": [],
        "history": [],
    }


# ---------------------------------------------------------------------------
# Benchmark directory fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def benchmark_dir(tmp_path):
    """Create a benchmark directory structure with grading.json files."""
    base = tmp_path / "benchmark"
    base.mkdir()

    for eval_idx in range(2):
        eval_dir = base / f"eval-{eval_idx}"
        eval_dir.mkdir()
        (eval_dir / "eval_metadata.json").write_text(json.dumps({"eval_id": eval_idx}))

        for config in ["with_skill", "without_skill"]:
            config_dir = eval_dir / config
            config_dir.mkdir()

            for run_idx in range(1, 3):
                run_dir = config_dir / f"run-{run_idx}"
                run_dir.mkdir()
                (run_dir / "outputs").mkdir()

                pass_rate = 0.80 if config == "with_skill" else 0.50
                grading = {
                    "expectations": [
                        {"text": "Does X correctly", "passed": True, "evidence": "Found X in output"},
                        {"text": "Handles edge case", "passed": pass_rate > 0.6, "evidence": "Checked"},
                    ],
                    "summary": {
                        "passed": 2 if pass_rate > 0.6 else 1,
                        "failed": 0 if pass_rate > 0.6 else 1,
                        "total": 2,
                        "pass_rate": pass_rate,
                    },
                    "execution_metrics": {"total_tool_calls": 10, "output_chars": 2000},
                    "timing": {"total_duration_seconds": 30.0 if config == "with_skill" else 25.0},
                    "claims": [],
                    "user_notes_summary": {"uncertainties": [], "needs_review": [], "workarounds": []},
                    "eval_feedback": {"suggestions": [], "overall": "good"},
                }
                (run_dir / "grading.json").write_text(json.dumps(grading, indent=2))

    return base
