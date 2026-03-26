"""Functional tests for gap_analysis.py — recommendation deduplication and scoring."""

import json
import sys
from pathlib import Path

import pytest

import gap_analysis as ga


# ---------------------------------------------------------------------------
# extract_skill_name
# ---------------------------------------------------------------------------
class TestExtractSkillName:
    def test_valid_frontmatter(self, tmp_path):
        p = tmp_path / "SKILL.md"
        p.write_text('---\nname: my-skill\ndescription: something\n---\nBody.\n')
        assert ga.extract_skill_name(p) == "my-skill"

    def test_quoted_name(self, tmp_path):
        p = tmp_path / "SKILL.md"
        p.write_text('---\nname: "quoted-skill"\ndescription: x\n---\n')
        assert ga.extract_skill_name(p) == "quoted-skill"

    def test_no_frontmatter(self, tmp_path):
        p = tmp_path / "SKILL.md"
        p.write_text("Just plain text, no frontmatter.")
        assert ga.extract_skill_name(p) is None

    def test_missing_name_field(self, tmp_path):
        p = tmp_path / "SKILL.md"
        p.write_text('---\ndescription: no name here\n---\n')
        assert ga.extract_skill_name(p) is None

    def test_file_not_found(self, tmp_path):
        p = tmp_path / "nonexistent.md"
        assert ga.extract_skill_name(p) is None


# ---------------------------------------------------------------------------
# scan_installed_skills
# ---------------------------------------------------------------------------
class TestScanInstalledSkills:
    def test_finds_skills_in_directory(self, skills_dir):
        installed = ga.scan_installed_skills([str(skills_dir)], str(skills_dir / "plugins"))
        assert "alpha-skill" in installed
        assert "beta-skill" in installed
        assert "gamma-skill" in installed

    def test_nonexistent_dirs_ignored(self, tmp_path):
        installed = ga.scan_installed_skills([str(tmp_path / "nope")], str(tmp_path / "also-nope"))
        assert installed == {}

    def test_empty_dir_returns_empty(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        installed = ga.scan_installed_skills([str(empty)], str(tmp_path / "plugins"))
        assert installed == {}


# ---------------------------------------------------------------------------
# analyze_history
# ---------------------------------------------------------------------------
class TestAnalyzeHistory:
    def test_counts_keywords(self, history_file):
        keywords, session_count = ga.analyze_history(str(history_file))
        assert session_count == 3  # s1, s2, s3
        assert keywords["something"] >= 1
        assert keywords["alpha"] >= 1

    def test_missing_history_returns_empty(self, tmp_path):
        keywords, session_count = ga.analyze_history(str(tmp_path / "missing.jsonl"))
        assert session_count == 0
        assert len(keywords) == 0

    def test_respects_max_entries(self, tmp_path):
        path = tmp_path / "big.jsonl"
        with open(path, "w") as f:
            for i in range(100):
                f.write(json.dumps({"display": f"word{i}", "sessionId": f"s{i}"}) + "\n")
        keywords, count = ga.analyze_history(str(path), max_entries=10)
        # Exactly 10 unique sessions in first 10 lines
        assert count == 10
        # Also confirm we didn't process all 100
        keywords_all, count_all = ga.analyze_history(str(path), max_entries=5000)
        assert count_all == 100
        assert count < count_all


# ---------------------------------------------------------------------------
# compute_activity_match
# ---------------------------------------------------------------------------
class TestComputeActivityMatch:
    def test_matching_keywords_score_higher(self):
        from collections import Counter
        keywords = Counter({"deploy": 10, "test": 5, "build": 3})
        rec_high = {"name": "deploy-skill", "why": "automate deploy", "type": "deploy", "steps": "deploy"}
        rec_low = {"name": "docs-skill", "why": "generate docs", "type": "documentation", "steps": ""}
        score_high = ga.compute_activity_match(rec_high, keywords)
        score_low = ga.compute_activity_match(rec_low, keywords)
        assert score_high > score_low

    def test_empty_keywords_returns_zero(self):
        from collections import Counter
        rec = {"name": "anything", "why": "something", "type": "x", "steps": "y"}
        assert ga.compute_activity_match(rec, Counter()) == 0.0

    def test_stopwords_excluded(self):
        from collections import Counter
        keywords = Counter({"the": 100, "and": 100, "for": 100})
        rec = {"name": "the-and-for", "why": "the and for", "type": "", "steps": ""}
        # Stopwords filtered, so score should be low or zero
        score = ga.compute_activity_match(rec, keywords)
        assert score == 0.0


# ---------------------------------------------------------------------------
# run_gap_analysis
# ---------------------------------------------------------------------------
class TestRunGapAnalysis:
    def test_separates_gaps_and_covered(self):
        recs = [
            {"name": "alpha-skill", "priority": "High", "type": "x", "why": "y", "steps": "", "tools": ""},
            {"name": "new-skill", "priority": "Medium", "type": "x", "why": "y", "steps": "", "tools": ""},
        ]
        installed = {"alpha-skill": "/path/to/SKILL.md"}
        from collections import Counter
        report = ga.run_gap_analysis(recs, installed, Counter(), 0)
        assert report["total_gaps"] == 1
        assert report["total_covered"] == 1
        assert report["gaps"][0]["name"] == "new-skill"
        assert report["already_covered"][0]["name"] == "alpha-skill"

    def test_fuzzy_matching_ignores_hyphens(self):
        recs = [{"name": "my-skill", "priority": "High", "type": "x", "why": "", "steps": "", "tools": ""}]
        installed = {"myskill": "/path"}  # no hyphens
        from collections import Counter
        report = ga.run_gap_analysis(recs, installed, Counter(), 0)
        assert report["total_covered"] == 1
        assert report["total_gaps"] == 0

    def test_priority_sorting(self):
        recs = [
            {"name": "low", "priority": "Low", "type": "", "why": "", "steps": "", "tools": ""},
            {"name": "high", "priority": "High", "type": "", "why": "", "steps": "", "tools": ""},
            {"name": "medium", "priority": "Medium", "type": "", "why": "", "steps": "", "tools": ""},
        ]
        from collections import Counter
        report = ga.run_gap_analysis(recs, {}, Counter(), 0)
        names = [g["name"] for g in report["gaps"]]
        assert names == ["high", "medium", "low"]

    def test_leading_slash_stripped(self):
        recs = [{"name": "/slash-skill", "priority": "High", "type": "", "why": "", "steps": "", "tools": ""}]
        from collections import Counter
        report = ga.run_gap_analysis(recs, {}, Counter(), 0)
        assert report["gaps"][0]["name"] == "slash-skill"

    def test_empty_recommendations(self):
        from collections import Counter
        report = ga.run_gap_analysis([], {}, Counter(), 5)
        assert report["total_gaps"] == 0
        assert report["total_covered"] == 0
        assert report["session_count"] == 5
