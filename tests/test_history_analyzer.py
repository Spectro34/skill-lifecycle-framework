"""Functional tests for history_analyzer.py — usage mining."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import history_analyzer as ha


# ---------------------------------------------------------------------------
# scan_skill_names
# ---------------------------------------------------------------------------
class TestScanSkillNames:
    def test_finds_all_skills(self, skills_dir):
        names = ha.scan_skill_names(str(skills_dir))
        assert set(names) == {"alpha-skill", "beta-skill", "gamma-skill"}

    def test_nonexistent_dir_returns_empty(self, tmp_path):
        names = ha.scan_skill_names(str(tmp_path / "nope"))
        assert names == []

    def test_skips_invalid_skill_md(self, tmp_path):
        d = tmp_path / "skills" / "bad-skill"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("No frontmatter here, just text.")
        names = ha.scan_skill_names(str(tmp_path / "skills"))
        assert names == []


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------
class TestAnalyze:
    def test_counts_invocations(self, history_file):
        report = ha.analyze(str(history_file), ["alpha-skill", "beta-skill", "gamma-skill"])
        skills = {s["name"]: s for s in report["skills"]}
        assert skills["alpha-skill"]["invocations"] == 2
        assert skills["beta-skill"]["invocations"] == 1
        assert skills["gamma-skill"]["invocations"] == 0

    def test_status_classification(self, tmp_path):
        now = datetime.now(timezone.utc)
        recent_ts = int(now.timestamp() * 1000)
        old_ts = int((now - timedelta(days=60)).timestamp() * 1000)

        path = tmp_path / "history.jsonl"
        entries = [
            {"display": "/active-skill do work", "timestamp": recent_ts},
            {"display": "/dormant-skill old work", "timestamp": old_ts},
        ]
        with open(path, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

        report = ha.analyze(str(path), ["active-skill", "dormant-skill", "missing-skill"])
        skills = {s["name"]: s for s in report["skills"]}
        assert skills["active-skill"]["status"] == "active"
        assert skills["dormant-skill"]["status"] == "dormant"
        assert skills["missing-skill"]["status"] == "never"

    def test_missing_history_returns_error(self, tmp_path):
        report = ha.analyze(str(tmp_path / "missing.jsonl"), ["some-skill"])
        assert "error" in report

    def test_summary_counts(self, tmp_path):
        now_ts = int(datetime.now(timezone.utc).timestamp() * 1000)
        path = tmp_path / "history.jsonl"
        with open(path, "w") as f:
            f.write(json.dumps({"display": "/active-skill x", "timestamp": now_ts}) + "\n")

        report = ha.analyze(str(path), ["active-skill", "never-skill"])
        assert report["skills_analyzed"] == 2
        assert report["active"] == 1
        assert report["never_used"] == 1

    def test_sorted_by_invocations_desc(self, history_file):
        report = ha.analyze(str(history_file), ["alpha-skill", "beta-skill", "gamma-skill"])
        invocations = [s["invocations"] for s in report["skills"]]
        assert invocations == sorted(invocations, reverse=True)

    def test_handles_malformed_json_lines(self, tmp_path):
        path = tmp_path / "bad.jsonl"
        with open(path, "w") as f:
            f.write("not valid json\n")
            f.write(json.dumps({"display": "/my-skill works", "timestamp": 1711400000000}) + "\n")
            f.write("{broken\n")

        report = ha.analyze(str(path), ["my-skill"])
        skills = {s["name"]: s for s in report["skills"]}
        assert skills["my-skill"]["invocations"] == 1

    def test_empty_history_file(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        report = ha.analyze(str(path), ["some-skill"])
        assert report["skills_analyzed"] == 1
        assert report["never_used"] == 1
