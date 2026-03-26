#!/usr/bin/env python3
"""State machine for the skill lifecycle orchestrator.

Manages a JSON state file at ~/.claude/skill-lifecycle-state.json.
Tracks skills through phases: RECOMMENDED → BUILDING → TESTING → DEPLOYED → MONITORING → CHURNED.

Usage:
    python3 lifecycle_state.py status
    python3 lifecycle_state.py add --name <skill-name> --phase RECOMMENDED [--data '{"key":"val"}']
    python3 lifecycle_state.py transition --name <skill-name> --to <PHASE>
    python3 lifecycle_state.py list --phase <PHASE>
    python3 lifecycle_state.py update-audit --name <skill-name> --f1 0.85 --quality-delta 0.22 --usage active
    python3 lifecycle_state.py mark-churned --name <skill-name> --reason "never used"
"""

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Prefer project-scoped state (.claude/), fall back to user-scoped (~/.claude/)
_project_state = Path(".claude") / "skill-lifecycle-state.json"
_user_state = Path.home() / ".claude" / "skill-lifecycle-state.json"
STATE_PATH = _project_state if _project_state.parent.exists() else _user_state

VALID_PHASES = {"RECOMMENDED", "BUILDING", "TESTING", "DEPLOYED", "MONITORING", "REBUILDING", "CHURNED"}

ALLOWED_TRANSITIONS = {
    "RECOMMENDED": {"BUILDING"},
    "BUILDING": {"TESTING"},
    "TESTING": {"DEPLOYED", "BUILDING"},  # back to BUILDING if failed and iterating
    "DEPLOYED": {"MONITORING"},
    "MONITORING": {"REBUILDING", "CHURNED"},
    "REBUILDING": {"TESTING"},
    "CHURNED": set(),  # terminal
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def default_state():
    return {
        "version": 1,
        "last_run": now_iso(),
        "current_phase": "IDLE",
        "project": os.getcwd(),
        "skills_in_flight": [],
        "installed_skills_snapshot": [],
        "research_output": None,
        "gap_analysis": None,
        "churn_candidates": [],
        "history": [],
    }


def load_state():
    if STATE_PATH.exists():
        with open(STATE_PATH) as f:
            return json.load(f)
    return default_state()


def save_state(state):
    state["last_run"] = now_iso()
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write
    fd, tmp = tempfile.mkstemp(dir=STATE_PATH.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, STATE_PATH)
    except Exception:
        os.unlink(tmp)
        raise


def find_skill(state, name):
    for skill in state["skills_in_flight"]:
        if skill["name"] == name:
            return skill
    return None


def cmd_status(state, _args):
    print(f"State file: {STATE_PATH}")
    print(f"Last run: {state['last_run']}")
    print(f"Current phase: {state['current_phase']}")
    print(f"Project: {state.get('project', 'unknown')}")
    print(f"Skills tracked: {len(state['skills_in_flight'])}")
    print()
    if state["skills_in_flight"]:
        print(f"{'Name':<30} {'Phase':<15} {'Last Audit':<22} {'F1':<8} {'Quality':<10}")
        print("-" * 85)
        for s in state["skills_in_flight"]:
            last_audit = s.get("last_audit", "-") or "-"
            f1 = s.get("test_results", {}).get("trigger_f1", "-")
            delta = s.get("test_results", {}).get("quality_delta", "-")
            print(f"{s['name']:<30} {s['phase']:<15} {str(last_audit):<22} {str(f1):<8} {str(delta):<10}")
    else:
        print("No skills currently tracked.")
    return 0


def cmd_add(state, args):
    if find_skill(state, args.name):
        print(f"Error: skill '{args.name}' already tracked.", file=sys.stderr)
        return 1
    if args.phase not in VALID_PHASES:
        print(f"Error: invalid phase '{args.phase}'. Valid: {VALID_PHASES}", file=sys.stderr)
        return 1
    extra = json.loads(args.data) if args.data else {}
    skill = {
        "name": args.name,
        "phase": args.phase,
        "recommended_at": now_iso(),
        "build_started_at": None,
        "deployed_at": None,
        "last_audit": None,
        "test_results": {},
        "audit_history": [],
        **extra,
    }
    state["skills_in_flight"].append(skill)
    save_state(state)
    print(f"Added '{args.name}' in phase {args.phase}.")
    return 0


def cmd_transition(state, args):
    skill = find_skill(state, args.name)
    if not skill:
        print(f"Error: skill '{args.name}' not found.", file=sys.stderr)
        return 1
    if args.to not in VALID_PHASES:
        print(f"Error: invalid target phase '{args.to}'.", file=sys.stderr)
        return 1
    current = skill["phase"]
    if args.to not in ALLOWED_TRANSITIONS.get(current, set()):
        print(f"Error: cannot transition from {current} to {args.to}.", file=sys.stderr)
        print(f"Allowed from {current}: {ALLOWED_TRANSITIONS.get(current, set())}", file=sys.stderr)
        return 1

    old_phase = skill["phase"]
    skill["phase"] = args.to

    if args.to == "BUILDING":
        skill["build_started_at"] = now_iso()
    elif args.to == "DEPLOYED":
        skill["deployed_at"] = now_iso()
    elif args.to == "CHURNED":
        skill["churned_at"] = now_iso()

    state["history"].append({
        "timestamp": now_iso(),
        "skill": args.name,
        "from": old_phase,
        "to": args.to,
    })
    save_state(state)
    print(f"Transitioned '{args.name}': {old_phase} → {args.to}")
    return 0


def cmd_list(state, args):
    matches = [s for s in state["skills_in_flight"] if s["phase"] == args.phase]
    if matches:
        for s in matches:
            print(s["name"])
    else:
        print(f"No skills in phase {args.phase}.")
    return 0


def cmd_update_audit(state, args):
    skill = find_skill(state, args.name)
    if not skill:
        print(f"Error: skill '{args.name}' not found.", file=sys.stderr)
        return 1

    audit_entry = {
        "timestamp": now_iso(),
        "trigger_f1": args.f1,
        "quality_delta": args.quality_delta,
        "usage": args.usage,
    }
    skill["last_audit"] = now_iso()
    skill["test_results"]["trigger_f1"] = args.f1
    skill["test_results"]["quality_delta"] = args.quality_delta
    skill["test_results"]["usage"] = args.usage
    skill["audit_history"].append(audit_entry)
    save_state(state)
    print(f"Updated audit for '{args.name}': F1={args.f1}, delta={args.quality_delta}, usage={args.usage}")
    return 0


def cmd_mark_churned(state, args):
    skill = find_skill(state, args.name)
    if not skill:
        print(f"Error: skill '{args.name}' not found.", file=sys.stderr)
        return 1
    skill["phase"] = "CHURNED"
    skill["churned_at"] = now_iso()
    skill["churn_reason"] = args.reason
    state["history"].append({
        "timestamp": now_iso(),
        "skill": args.name,
        "from": skill["phase"],
        "to": "CHURNED",
        "reason": args.reason,
    })
    save_state(state)
    print(f"Marked '{args.name}' as CHURNED: {args.reason}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Skill lifecycle state manager")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="Show current state")

    p_add = sub.add_parser("add", help="Add a skill to tracking")
    p_add.add_argument("--name", required=True)
    p_add.add_argument("--phase", default="RECOMMENDED")
    p_add.add_argument("--data", default=None, help="Extra JSON data")

    p_trans = sub.add_parser("transition", help="Transition a skill's phase")
    p_trans.add_argument("--name", required=True)
    p_trans.add_argument("--to", required=True)

    p_list = sub.add_parser("list", help="List skills in a phase")
    p_list.add_argument("--phase", required=True)

    p_audit = sub.add_parser("update-audit", help="Update audit data for a skill")
    p_audit.add_argument("--name", required=True)
    p_audit.add_argument("--f1", type=float, required=True)
    p_audit.add_argument("--quality-delta", type=float, required=True)
    p_audit.add_argument("--usage", required=True, choices=["active", "dormant", "never"])

    p_churn = sub.add_parser("mark-churned", help="Mark a skill as churned")
    p_churn.add_argument("--name", required=True)
    p_churn.add_argument("--reason", required=True)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1

    state = load_state()
    commands = {
        "status": cmd_status,
        "add": cmd_add,
        "transition": cmd_transition,
        "list": cmd_list,
        "update-audit": cmd_update_audit,
        "mark-churned": cmd_mark_churned,
    }
    return commands[args.command](state, args)


if __name__ == "__main__":
    sys.exit(main() or 0)
