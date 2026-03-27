#!/usr/bin/env bash
# Uninstall the Skill Lifecycle Framework.
# Removes skills, hooks, and settings entries.

set -euo pipefail

CLAUDE_DIR="$HOME/.claude"

echo "=== Skill Lifecycle Framework — Uninstall ==="
echo ""

# Remove skills
for name in skill-lifecycle evaluate-skills skill-evaluator skill-creator; do
    if [ -d "$CLAUDE_DIR/skills/$name" ]; then
        rm -rf "$CLAUDE_DIR/skills/$name"
        echo "  Removed skill: $name"
    fi
done

# Remove hooks
for hook in on-project-open.sh log-skill-usage.sh; do
    if [ -f "$CLAUDE_DIR/hooks/$hook" ]; then
        rm "$CLAUDE_DIR/hooks/$hook"
        echo "  Removed hook: $hook"
    fi
done

# Remove hook entries from settings.json
if [ -f "$CLAUDE_DIR/settings.json" ]; then
    python3 << 'PYEOF'
import json
from pathlib import Path

settings_path = Path.home() / ".claude" / "settings.json"
with open(settings_path) as f:
    settings = json.load(f)

hooks = settings.get("hooks", {})
for event in ["SessionStart", "PostToolUse"]:
    if event in hooks:
        hooks[event] = [
            h for h in hooks[event]
            if not any("skill-lifecycle" in str(hook) or "log-skill-usage" in str(hook) or "on-project-open" in str(hook)
                       for hook in h.get("hooks", []))
        ]
        if not hooks[event]:
            del hooks[event]

if not hooks:
    settings.pop("hooks", None)

with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")
print("  Cleaned settings.json")
PYEOF
fi

echo ""
echo "Uninstalled. Your other Claude Code settings are preserved."
