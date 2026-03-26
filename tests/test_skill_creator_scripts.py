"""Functional tests for skill-creator scripts: utils, quick_validate, aggregate_benchmark, package_skill."""

import json
import math
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from utils import parse_skill_md
from aggregate_benchmark import calculate_stats, load_run_results, aggregate_results, generate_benchmark, generate_markdown


# ===========================================================================
# Test: utils.parse_skill_md
# ===========================================================================
class TestParseSkillMd:
    def test_basic_parsing(self, skill_dir):
        name, desc, content = parse_skill_md(skill_dir)
        assert name == "test-skill"
        assert desc == "A test skill for validation"
        assert "Body content here." in content

    def test_quoted_name(self, tmp_path):
        d = tmp_path / "quoted"
        d.mkdir()
        (d / "SKILL.md").write_text('---\nname: "my-skill"\ndescription: \'desc\'\n---\nBody\n')
        name, desc, _ = parse_skill_md(d)
        assert name == "my-skill"
        assert desc == "desc"

    def test_multiline_description_folded(self, tmp_path):
        d = tmp_path / "multi"
        d.mkdir()
        (d / "SKILL.md").write_text('---\nname: multi\ndescription: >\n  line one\n  line two\n---\nBody\n')
        name, desc, _ = parse_skill_md(d)
        assert "line one" in desc
        assert "line two" in desc

    def test_multiline_description_literal(self, tmp_path):
        d = tmp_path / "literal"
        d.mkdir()
        (d / "SKILL.md").write_text('---\nname: literal\ndescription: |\n  line one\n  line two\n---\nBody\n')
        _, desc, _ = parse_skill_md(d)
        assert "line one" in desc
        assert "line two" in desc

    def test_missing_frontmatter_raises(self, tmp_path):
        d = tmp_path / "bad"
        d.mkdir()
        (d / "SKILL.md").write_text("No frontmatter at all.")
        with pytest.raises(ValueError, match="missing frontmatter"):
            parse_skill_md(d)

    def test_unclosed_frontmatter_raises(self, tmp_path):
        d = tmp_path / "unclosed"
        d.mkdir()
        (d / "SKILL.md").write_text("---\nname: unclosed\ndescription: x\nNo closing dashes")
        with pytest.raises(ValueError, match="missing frontmatter"):
            parse_skill_md(d)


# ===========================================================================
# Test: quick_validate (import indirectly to avoid yaml dependency issues)
# ===========================================================================
class TestQuickValidate:
    @pytest.fixture(autouse=True)
    def _import_validate(self):
        """Try to import quick_validate; skip if yaml is not available."""
        try:
            from quick_validate import validate_skill
            self.validate_skill = validate_skill
        except ImportError:
            pytest.skip("PyYAML not installed, skipping quick_validate tests")

    def test_valid_skill(self, skill_dir):
        valid, msg = self.validate_skill(skill_dir)
        assert valid is True

    def test_missing_skill_md(self, tmp_path):
        d = tmp_path / "empty-skill"
        d.mkdir()
        valid, msg = self.validate_skill(d)
        assert valid is False
        assert "SKILL.md not found" in msg

    def test_no_frontmatter(self, tmp_path):
        d = tmp_path / "no-fm"
        d.mkdir()
        (d / "SKILL.md").write_text("Just text.")
        valid, msg = self.validate_skill(d)
        assert valid is False

    def test_missing_name(self, tmp_path):
        d = tmp_path / "no-name"
        d.mkdir()
        (d / "SKILL.md").write_text("---\ndescription: has desc\n---\n")
        valid, msg = self.validate_skill(d)
        assert valid is False
        assert "name" in msg.lower()

    def test_missing_description(self, tmp_path):
        d = tmp_path / "no-desc"
        d.mkdir()
        (d / "SKILL.md").write_text("---\nname: no-desc\n---\n")
        valid, msg = self.validate_skill(d)
        assert valid is False
        assert "description" in msg.lower()

    def test_non_kebab_case_name(self, tmp_path):
        d = tmp_path / "bad-name"
        d.mkdir()
        (d / "SKILL.md").write_text("---\nname: BadName\ndescription: x\n---\n")
        valid, msg = self.validate_skill(d)
        assert valid is False
        assert "kebab" in msg.lower()

    def test_name_with_leading_hyphen(self, tmp_path):
        d = tmp_path / "hyphen"
        d.mkdir()
        (d / "SKILL.md").write_text("---\nname: -leading\ndescription: x\n---\n")
        valid, msg = self.validate_skill(d)
        assert valid is False

    def test_name_too_long(self, tmp_path):
        d = tmp_path / "long-name"
        d.mkdir()
        long_name = "a" * 65
        (d / "SKILL.md").write_text(f"---\nname: {long_name}\ndescription: x\n---\n")
        valid, msg = self.validate_skill(d)
        assert valid is False
        assert "64" in msg

    def test_description_with_angle_brackets(self, tmp_path):
        d = tmp_path / "angles"
        d.mkdir()
        (d / "SKILL.md").write_text("---\nname: angles\ndescription: has <html> tags\n---\n")
        valid, msg = self.validate_skill(d)
        assert valid is False
        assert "angle" in msg.lower()

    def test_unexpected_frontmatter_key(self, tmp_path):
        d = tmp_path / "extra-key"
        d.mkdir()
        (d / "SKILL.md").write_text("---\nname: extra-key\ndescription: x\nfoo: bar\n---\n")
        valid, msg = self.validate_skill(d)
        assert valid is False
        assert "foo" in msg.lower()


# ===========================================================================
# Test: aggregate_benchmark — calculate_stats
# ===========================================================================
class TestCalculateStats:
    def test_basic_stats(self):
        stats = calculate_stats([1.0, 2.0, 3.0, 4.0, 5.0])
        assert stats["mean"] == 3.0
        assert stats["min"] == 1.0
        assert stats["max"] == 5.0
        assert stats["stddev"] > 0

    def test_single_value(self):
        stats = calculate_stats([42.0])
        assert stats["mean"] == 42.0
        assert stats["stddev"] == 0.0
        assert stats["min"] == 42.0
        assert stats["max"] == 42.0

    def test_empty_list(self):
        stats = calculate_stats([])
        assert stats["mean"] == 0.0
        assert stats["stddev"] == 0.0

    def test_identical_values(self):
        stats = calculate_stats([5.0, 5.0, 5.0])
        assert stats["mean"] == 5.0
        assert stats["stddev"] == 0.0

    def test_sample_stddev(self):
        # Verify it uses sample stddev (n-1), not population stddev
        stats = calculate_stats([2.0, 4.0])
        # Sample stddev of [2, 4] = sqrt(((2-3)^2 + (4-3)^2) / 1) = sqrt(2) ≈ 1.4142
        assert abs(stats["stddev"] - math.sqrt(2)) < 0.001


# ===========================================================================
# Test: aggregate_benchmark — load_run_results
# ===========================================================================
class TestLoadRunResults:
    def test_loads_benchmark_dir(self, benchmark_dir):
        results = load_run_results(benchmark_dir)
        assert "with_skill" in results
        assert "without_skill" in results
        assert len(results["with_skill"]) == 4  # 2 evals × 2 runs
        assert len(results["without_skill"]) == 4

    def test_extracts_pass_rate(self, benchmark_dir):
        results = load_run_results(benchmark_dir)
        for run in results["with_skill"]:
            assert run["pass_rate"] == 0.80
        for run in results["without_skill"]:
            assert run["pass_rate"] == 0.50

    def test_empty_dir_returns_empty(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        results = load_run_results(empty)
        assert results == {}

    def test_legacy_layout_with_runs_subdir(self, benchmark_dir):
        """Test that runs/ subdirectory layout also works."""
        legacy = benchmark_dir.parent / "legacy"
        legacy.mkdir()
        runs_dir = legacy / "runs"
        # Move eval dirs into runs/
        import shutil
        shutil.copytree(benchmark_dir, runs_dir)
        results = load_run_results(legacy)
        assert "with_skill" in results


# ===========================================================================
# Test: aggregate_benchmark — aggregate_results
# ===========================================================================
class TestAggregateResults:
    def test_computes_delta(self, benchmark_dir):
        results = load_run_results(benchmark_dir)
        summary = aggregate_results(results)
        assert "delta" in summary
        # with_skill (0.80) - without_skill (0.50) = +0.30
        delta_pr = float(summary["delta"]["pass_rate"])
        assert abs(delta_pr - 0.30) < 0.01

    def test_single_config_no_crash(self):
        results = {"only_config": [
            {"pass_rate": 0.75, "time_seconds": 20.0, "tokens": 1000},
        ]}
        summary = aggregate_results(results)
        assert "only_config" in summary
        assert "delta" in summary


# ===========================================================================
# Test: aggregate_benchmark — generate_benchmark
# ===========================================================================
class TestGenerateBenchmark:
    def test_full_benchmark_structure(self, benchmark_dir):
        bench = generate_benchmark(benchmark_dir, skill_name="test-skill")
        assert bench["metadata"]["skill_name"] == "test-skill"
        assert isinstance(bench["runs"], list)
        assert len(bench["runs"]) > 0
        assert "run_summary" in bench
        assert "delta" in bench["run_summary"]

    def test_generate_markdown_output(self, benchmark_dir):
        bench = generate_benchmark(benchmark_dir, skill_name="test-skill")
        md = generate_markdown(bench)
        assert "# Skill Benchmark: test-skill" in md
        assert "Pass Rate" in md
        assert "Delta" in md


# ===========================================================================
# Test: package_skill — should_exclude
# ===========================================================================
class TestPackageSkillExclusions:
    @pytest.fixture(autouse=True)
    def _import_package(self):
        try:
            import importlib
            import sys as _sys
            # package_skill imports from scripts.quick_validate, adjust path
            creator_dir = Path(__file__).resolve().parent.parent / ".claude" / "skills" / "skill-creator"
            if str(creator_dir) not in _sys.path:
                _sys.path.insert(0, str(creator_dir))
            from scripts.package_skill import should_exclude, package_skill
            self.should_exclude = should_exclude
            self.package_skill = package_skill
        except ImportError as e:
            pytest.skip(f"Cannot import package_skill: {e}")

    def test_exclude_pycache(self):
        assert self.should_exclude(Path("skill/__pycache__/foo.pyc")) is True

    def test_exclude_pyc_files(self):
        assert self.should_exclude(Path("skill/module.pyc")) is True

    def test_exclude_ds_store(self):
        assert self.should_exclude(Path("skill/.DS_Store")) is True

    def test_exclude_root_evals(self):
        assert self.should_exclude(Path("skill/evals/test.json")) is True

    def test_allow_normal_files(self):
        assert self.should_exclude(Path("skill/SKILL.md")) is False
        assert self.should_exclude(Path("skill/scripts/utils.py")) is False

    def test_allow_nested_evals(self):
        # evals/ excluded only at root, not deeper
        assert self.should_exclude(Path("skill/scripts/evals/data.json")) is False

    def test_package_creates_zip(self, skill_dir):
        output = self.package_skill(skill_dir)
        assert output is not None
        assert output.suffix == ".skill"
        assert zipfile.is_zipfile(output)
        # Verify the zip actually contains SKILL.md
        with zipfile.ZipFile(output, "r") as zf:
            names = zf.namelist()
            assert any("SKILL.md" in n for n in names), f"SKILL.md not found in zip: {names}"
            assert len(names) > 0

    def test_package_missing_dir_returns_none(self, tmp_path):
        result = self.package_skill(tmp_path / "nonexistent")
        assert result is None

    def test_package_no_skill_md_returns_none(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        result = self.package_skill(d)
        assert result is None
