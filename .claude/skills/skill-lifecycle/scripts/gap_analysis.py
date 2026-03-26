#!/usr/bin/env python3
"""Cross-reference skill recommendations against installed skills and user history.

Reads evaluate-skills recommendations (from stdin as JSON), scans installed skills,
mines history.jsonl for user behavior, and produces a ranked gap report.

Usage:
    echo '<recommendations-json>' | python3 gap_analysis.py \
        --skills-dirs ~/.claude/skills .claude/skills \
        --plugins-dir ~/.claude/plugins/marketplaces \
        --history ~/.claude/history.jsonl

Input JSON format (from evaluate-skills):
    [{"name": "skill-name", "priority": "High", "type": "...", "why": "...", "steps": "...", "tools": "..."}]

Output: JSON gap report to stdout.
"""

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def scan_installed_skills(skills_dirs, plugins_dir):
    """Find all installed skill names by scanning SKILL.md frontmatter."""
    installed = {}

    # Scan user/project skill directories
    for d in skills_dirs:
        p = Path(d).expanduser()
        if not p.exists():
            continue
        for skill_md in p.glob("*/SKILL.md"):
            name = extract_skill_name(skill_md)
            if name:
                installed[name] = str(skill_md)

    # Scan plugin marketplace
    plugins_path = Path(plugins_dir).expanduser()
    if plugins_path.exists():
        for skill_md in plugins_path.glob("**/skills/*/SKILL.md"):
            name = extract_skill_name(skill_md)
            if name:
                installed[name] = str(skill_md)

    return installed


def extract_skill_name(skill_md_path):
    """Extract the 'name' field from SKILL.md YAML frontmatter."""
    try:
        text = skill_md_path.read_text(errors="replace")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    end = text.find("---", 3)
    if end == -1:
        return None
    frontmatter = text[3:end]
    for line in frontmatter.splitlines():
        m = re.match(r"^name:\s*(.+)", line)
        if m:
            return m.group(1).strip().strip("\"'")
    return None


def analyze_history(history_path, max_entries=5000):
    """Mine history.jsonl for user behavior patterns.

    Returns keyword frequency counts and session count.
    """
    keywords = Counter()
    session_count = 0
    seen_sessions = set()

    path = Path(history_path).expanduser()
    if not path.exists():
        return keywords, 0

    try:
        with open(path) as f:
            for i, line in enumerate(f):
                if i >= max_entries:
                    break
                try:
                    entry = json.loads(line.strip())
                except (json.JSONDecodeError, ValueError):
                    continue

                sid = entry.get("sessionId", "")
                if sid and sid not in seen_sessions:
                    seen_sessions.add(sid)
                    session_count += 1

                display = entry.get("display", "")
                if not display:
                    continue

                # Extract meaningful words (3+ chars, lowercase)
                words = re.findall(r"\b[a-zA-Z]{3,}\b", display.lower())
                keywords.update(words)
    except OSError:
        pass

    return keywords, session_count


def compute_activity_match(recommendation, keywords):
    """Score how well a recommendation matches user activity patterns.

    Higher score = user's history suggests they'd use this skill more.
    """
    text = f"{recommendation.get('name', '')} {recommendation.get('why', '')} {recommendation.get('type', '')} {recommendation.get('steps', '')}"
    words = set(re.findall(r"\b[a-zA-Z]{3,}\b", text.lower()))

    # Ignore very common words
    stopwords = {"the", "and", "for", "that", "this", "with", "from", "will", "would",
                 "should", "could", "have", "been", "also", "use", "using", "used",
                 "run", "running", "file", "files", "check", "create", "add", "new"}
    words -= stopwords

    if not words:
        return 0.0

    score = sum(keywords.get(w, 0) for w in words)
    return round(score / len(words), 2) if words else 0.0


def run_gap_analysis(recommendations, installed, keywords, session_count):
    """Produce the gap report."""
    gaps = []
    already_covered = []

    for rec in recommendations:
        name = rec.get("name", "").strip().lstrip("/")

        # Check if already installed (fuzzy match on name)
        is_installed = False
        matched_skill = None
        for installed_name in installed:
            if name == installed_name or name.replace("-", "") == installed_name.replace("-", ""):
                is_installed = True
                matched_skill = installed_name
                break

        activity_score = compute_activity_match(rec, keywords)

        entry = {
            "name": name,
            "priority": rec.get("priority", "Medium"),
            "type": rec.get("type", "unknown"),
            "why": rec.get("why", ""),
            "steps": rec.get("steps", ""),
            "tools": rec.get("tools", ""),
            "already_installed": is_installed,
            "matched_skill": matched_skill,
            "activity_match_score": activity_score,
        }

        if is_installed:
            already_covered.append(entry)
        else:
            gaps.append(entry)

    # Sort gaps: high priority first, then by activity match
    priority_order = {"high": 0, "medium": 1, "low": 2}
    gaps.sort(key=lambda g: (
        priority_order.get(g["priority"].lower(), 1),
        -g["activity_match_score"],
    ))

    return {
        "gaps": gaps,
        "already_covered": already_covered,
        "total_recommendations": len(recommendations),
        "total_gaps": len(gaps),
        "total_covered": len(already_covered),
        "session_count": session_count,
        "installed_skills": list(installed.keys()),
    }


def main():
    parser = argparse.ArgumentParser(description="Skill gap analysis")
    parser.add_argument("--skills-dirs", nargs="+", default=["~/.claude/skills", ".claude/skills"])
    parser.add_argument("--plugins-dir", default="~/.claude/plugins/marketplaces")
    parser.add_argument("--history", default="~/.claude/history.jsonl")
    args = parser.parse_args()

    # Read recommendations from stdin
    try:
        recommendations = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Error reading recommendations JSON from stdin: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(recommendations, list):
        print("Error: expected a JSON array of recommendations.", file=sys.stderr)
        sys.exit(1)

    installed = scan_installed_skills(args.skills_dirs, args.plugins_dir)
    keywords, session_count = analyze_history(args.history)
    report = run_gap_analysis(recommendations, installed, keywords, session_count)

    json.dump(report, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
