#!/usr/bin/env python3
"""Decision engine for skill churn: keep, fix, rewrite, or remove.

Reads the lifecycle state file and applies a decision tree based on
the latest audit data for each tracked skill.

Usage:
    python3 churn_decision.py --state ~/.claude/skill-lifecycle-state.json

Output: JSON actions list to stdout.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# --- Thresholds (keep in sync with references/thresholds.md) ---
F1_BROKEN = 0.50          # Below this → fix description
F1_GOOD = 0.80            # Above this → healthy
QUALITY_DELTA_MIN = 0.05  # Below 5% improvement → not worth it
DORMANT_DAYS = 30         # No usage in this many days → review
DECLINING_AUDITS = 3      # F1 declining across this many audits → investigate


def days_since(iso_timestamp):
    """Return days between now and an ISO timestamp, or None."""
    if not iso_timestamp:
        return None
    try:
        dt = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - dt
        return delta.days
    except (ValueError, TypeError):
        return None


def is_f1_declining(audit_history, min_audits=DECLINING_AUDITS):
    """Check if F1 has been declining across recent audits."""
    if len(audit_history) < min_audits:
        return False
    recent = audit_history[-min_audits:]
    f1_values = [a.get("trigger_f1") for a in recent if a.get("trigger_f1") is not None]
    if len(f1_values) < min_audits:
        return False
    # Check if each value is less than or equal to the previous
    return all(f1_values[i] <= f1_values[i - 1] for i in range(1, len(f1_values)))


def decide(skill):
    """Apply the decision tree to a single skill. Returns an action dict or None."""
    phase = skill.get("phase", "")
    test_results = skill.get("test_results", {})
    audit_history = skill.get("audit_history", [])

    f1 = test_results.get("trigger_f1")
    quality_delta = test_results.get("quality_delta")
    usage = test_results.get("usage", "unknown")

    # Parse quality_delta if it's a string like "+22%"
    if isinstance(quality_delta, str):
        try:
            quality_delta = float(quality_delta.strip("%+")) / 100.0
        except (ValueError, TypeError):
            quality_delta = None

    actions = []

    # Rule 1: Broken triggering
    if f1 is not None and f1 < F1_BROKEN:
        actions.append({
            "skill": skill["name"],
            "action": "FIX_DESCRIPTION",
            "reason": f"Trigger F1 score ({f1:.2f}) is below threshold ({F1_BROKEN})",
            "evidence": {"trigger_f1": f1, "threshold": F1_BROKEN},
            "escalation": "REWRITE_OR_REMOVE",  # if fix doesn't work
        })

    # Rule 2: No quality improvement
    if quality_delta is not None and quality_delta < QUALITY_DELTA_MIN:
        actions.append({
            "skill": skill["name"],
            "action": "REWRITE_OR_REMOVE",
            "reason": f"Quality delta ({quality_delta:.1%}) below minimum ({QUALITY_DELTA_MIN:.0%})",
            "evidence": {"quality_delta": quality_delta, "threshold": QUALITY_DELTA_MIN},
        })

    # Rule 3: Dormant
    if usage in ("dormant", "never"):
        last_audit_days = days_since(skill.get("last_audit"))
        deployed_days = days_since(skill.get("deployed_at"))
        age_days = deployed_days if deployed_days else last_audit_days

        if usage == "never" or (age_days is not None and age_days >= DORMANT_DAYS):
            actions.append({
                "skill": skill["name"],
                "action": "REVIEW_FOR_REMOVAL",
                "reason": f"Skill {'never used' if usage == 'never' else f'dormant for {age_days}+ days'}",
                "evidence": {"usage": usage, "days_since_deploy": age_days},
            })

    # Rule 4: Declining F1 trend
    if is_f1_declining(audit_history):
        recent_f1s = [a.get("trigger_f1") for a in audit_history[-DECLINING_AUDITS:]]
        actions.append({
            "skill": skill["name"],
            "action": "INVESTIGATE",
            "reason": f"F1 declining across last {DECLINING_AUDITS} audits: {recent_f1s}",
            "evidence": {"f1_trend": recent_f1s},
        })

    return actions


def main():
    parser = argparse.ArgumentParser(description="Skill churn decision engine")
    parser.add_argument("--state", default=str(Path.home() / ".claude" / "skill-lifecycle-state.json"))
    args = parser.parse_args()

    state_path = Path(args.state)
    if not state_path.exists():
        print("Error: state file not found.", file=sys.stderr)
        sys.exit(1)

    with open(state_path) as f:
        state = json.load(f)

    all_actions = []
    for skill in state.get("skills_in_flight", []):
        # Only evaluate deployed/monitoring skills (not ones still being built)
        if skill.get("phase") in ("DEPLOYED", "MONITORING"):
            actions = decide(skill)
            all_actions.extend(actions)

    # Deduplicate: if a skill has multiple actions, keep the most severe
    severity_order = {"REWRITE_OR_REMOVE": 0, "FIX_DESCRIPTION": 1, "REVIEW_FOR_REMOVAL": 2, "INVESTIGATE": 3}
    seen = {}
    for action in all_actions:
        name = action["skill"]
        if name not in seen or severity_order.get(action["action"], 99) < severity_order.get(seen[name]["action"], 99):
            seen[name] = action

    result = {
        "actions": list(seen.values()),
        "total_skills_evaluated": len([s for s in state.get("skills_in_flight", []) if s.get("phase") in ("DEPLOYED", "MONITORING")]),
        "total_actions": len(seen),
    }

    json.dump(result, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
