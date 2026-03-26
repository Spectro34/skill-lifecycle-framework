#!/usr/bin/env python3
"""Standalone usage analyzer for Claude Code skills.

Mines ~/.claude/history.jsonl to determine which skills are actually invoked,
how often, and when they were last used. Can run outside a Claude session.

Usage:
    python3 history_analyzer.py [--skills-dir ~/.claude/skills] [--history ~/.claude/history.jsonl]

Output: JSON usage report to stdout.
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


def scan_skill_names(skills_dir):
    """Get all skill names from a skills directory."""
    names = []
    p = Path(skills_dir).expanduser()
    if not p.exists():
        return names
    for skill_md in p.glob("*/SKILL.md"):
        try:
            text = skill_md.read_text(errors="replace")
        except OSError:
            continue
        if not text.startswith("---"):
            continue
        end = text.find("---", 3)
        if end == -1:
            continue
        for line in text[3:end].splitlines():
            m = re.match(r"^name:\s*(.+)", line)
            if m:
                names.append(m.group(1).strip().strip("\"'"))
                break
    return names


def analyze(history_path, skill_names):
    """Parse history.jsonl and count skill invocations."""
    invocations = Counter()
    last_used = {}
    keyword_hits = defaultdict(Counter)  # skill -> session keywords

    path = Path(history_path).expanduser()
    if not path.exists():
        return {"error": f"History file not found: {history_path}"}

    # Build regex patterns for direct invocations
    patterns = {}
    for name in skill_names:
        patterns[name] = re.compile(rf"(?:^|[\s/])(?:{re.escape(name)})\b", re.IGNORECASE)

    try:
        with open(path) as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                except (json.JSONDecodeError, ValueError):
                    continue

                display = entry.get("display", "")
                timestamp = entry.get("timestamp")
                if not display:
                    continue

                for name, pattern in patterns.items():
                    if pattern.search(display):
                        invocations[name] += 1
                        if timestamp:
                            ts = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
                            iso = ts.isoformat()
                            if name not in last_used or iso > last_used[name]:
                                last_used[name] = iso
    except OSError as e:
        return {"error": str(e)}

    now = datetime.now(timezone.utc)
    results = []
    for name in skill_names:
        count = invocations.get(name, 0)
        last = last_used.get(name)

        if last:
            try:
                last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                days_ago = (now - last_dt).days
            except (ValueError, TypeError):
                days_ago = None
        else:
            days_ago = None

        if count == 0:
            status = "never"
        elif days_ago is not None and days_ago > 30:
            status = "dormant"
        else:
            status = "active"

        results.append({
            "name": name,
            "invocations": count,
            "last_used": last,
            "days_since_last_use": days_ago,
            "status": status,
        })

    results.sort(key=lambda r: (-r["invocations"], r["name"]))

    return {
        "skills_analyzed": len(skill_names),
        "active": sum(1 for r in results if r["status"] == "active"),
        "dormant": sum(1 for r in results if r["status"] == "dormant"),
        "never_used": sum(1 for r in results if r["status"] == "never"),
        "skills": results,
    }


def main():
    parser = argparse.ArgumentParser(description="Skill usage analyzer")
    parser.add_argument("--skills-dir", default="~/.claude/skills")
    parser.add_argument("--history", default="~/.claude/history.jsonl")
    args = parser.parse_args()

    skill_names = scan_skill_names(args.skills_dir)
    if not skill_names:
        print(json.dumps({"error": "No skills found", "skills_dir": args.skills_dir}))
        sys.exit(1)

    report = analyze(args.history, skill_names)
    json.dump(report, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
