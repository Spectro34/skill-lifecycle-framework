#!/usr/bin/env bash
# Install the Skill Lifecycle Framework globally.
# Skills, hooks, and settings get installed to ~/.claude/ so they work in every project.
#
# Usage: git clone <repo> && cd skill-lifecycle-framework && bash install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
SKILLS_DIR="$CLAUDE_DIR/skills"
SETTINGS_FILE="$CLAUDE_DIR/settings.json"

echo "=== Skill Lifecycle Framework — Install ==="
echo ""

# --- Step 1: Install skills ---
echo "Installing skills to $SKILLS_DIR..."
for skill_dir in "$SCRIPT_DIR/.claude/skills"/*/; do
    skill_name="$(basename "$skill_dir")"
    target="$SKILLS_DIR/$skill_name"

    if [ -d "$target" ]; then
        echo "  Updating: $skill_name"
        rm -rf "$target"
    else
        echo "  Installing: $skill_name"
    fi
    cp -r "$skill_dir" "$target"
done

# --- Step 2: Install hooks ---
echo ""
echo "Installing hooks..."
mkdir -p "$CLAUDE_DIR/hooks"
cp "$SCRIPT_DIR/.claude/hooks/on-project-open.sh" "$CLAUDE_DIR/hooks/"
cp "$SCRIPT_DIR/.claude/hooks/log-skill-usage.sh" "$CLAUDE_DIR/hooks/"
chmod +x "$CLAUDE_DIR/hooks/on-project-open.sh" "$CLAUDE_DIR/hooks/log-skill-usage.sh"
echo "  Installed: on-project-open.sh (auto-detect new projects)"
echo "  Installed: log-skill-usage.sh (track skill usage)"

# --- Step 3: Wire hooks into global settings ---
echo ""
echo "Configuring hooks in settings..."

if [ ! -f "$SETTINGS_FILE" ]; then
    echo '{}' > "$SETTINGS_FILE"
fi

# Use Python to safely merge hooks into existing settings (preserves everything else)
python3 << 'PYEOF'
import json, sys
from pathlib import Path

settings_path = Path.home() / ".claude" / "settings.json"
hooks_dir = Path.home() / ".claude" / "hooks"

with open(settings_path) as f:
    settings = json.load(f)

if "hooks" not in settings:
    settings["hooks"] = {}

# Add SessionStart hook (new project detection)
session_hooks = settings["hooks"].get("SessionStart", [])
hook_cmd = f"bash {hooks_dir}/on-project-open.sh"
already_installed = any(
    h.get("hooks", [{}])[0].get("command", "") == hook_cmd
    if isinstance(h, dict) and "hooks" in h else False
    for h in session_hooks
)
if not already_installed:
    session_hooks.append({
        "hooks": [{"type": "command", "command": hook_cmd, "timeout": 5}]
    })
    settings["hooks"]["SessionStart"] = session_hooks
    print("  Added: SessionStart hook (new project detection)")
else:
    print("  Already configured: SessionStart hook")

# Add PostToolUse hook (skill usage tracking)
post_hooks = settings["hooks"].get("PostToolUse", [])
log_cmd = f"bash {hooks_dir}/log-skill-usage.sh"
already_installed = any(
    h.get("hooks", [{}])[0].get("command", "") == log_cmd
    if isinstance(h, dict) and "hooks" in h else False
    for h in post_hooks
)
if not already_installed:
    post_hooks.append({
        "matcher": "Skill",
        "hooks": [{"type": "command", "command": log_cmd, "timeout": 3, "async": True}]
    })
    settings["hooks"]["PostToolUse"] = post_hooks
    print("  Added: PostToolUse hook (skill usage tracking)")
else:
    print("  Already configured: PostToolUse hook")

with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")
PYEOF

# --- Step 4: Initialize state ---
echo ""
SCANNED_FILE="$CLAUDE_DIR/skill-lifecycle-scanned-projects.json"
if [ ! -f "$SCANNED_FILE" ]; then
    echo '{"projects":{}}' > "$SCANNED_FILE"
    echo "Initialized project tracking state."
fi

# --- Done ---
echo ""
echo "=== Installed ==="
echo ""
echo "Skills:"
for skill_dir in "$SCRIPT_DIR/.claude/skills"/*/; do
    echo "  /$(basename "$skill_dir")"
done
echo ""
echo "Hooks:"
echo "  SessionStart → auto-detect new projects"
echo "  PostToolUse  → track skill usage"
echo ""
echo "What happens next:"
echo "  1. Open ANY project with Claude Code"
echo "  2. On first visit, Claude suggests: /skill-lifecycle research"
echo "  3. Framework scans the project and recommends skills"
echo "  4. Run /skill-lifecycle monitor anytime to check skill health"
echo ""
echo "To uninstall: bash $(dirname "$0")/uninstall.sh"
