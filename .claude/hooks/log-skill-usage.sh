#!/usr/bin/env bash
# Log skill invocations for monitoring.
# Fires on PostToolUse for the Skill tool (async — doesn't block).
# Appends to ~/.claude/skill-invocation-log.jsonl
#
# Each entry: {"skill": "name", "timestamp": "ISO", "session_id": "uuid", "project": "/path"}

set -euo pipefail

HOOK_INPUT=$(cat)
LOG_FILE="$HOME/.claude/skill-invocation-log.jsonl"

# Extract skill name from tool input
SKILL_NAME=$(echo "$HOOK_INPUT" | jq -r '.tool_input.skill // .tool_input.name // "unknown"' 2>/dev/null || echo "unknown")
SESSION_ID=$(echo "$HOOK_INPUT" | jq -r '.session_id // "unknown"' 2>/dev/null || echo "unknown")
PROJECT_DIR=$(echo "$HOOK_INPUT" | jq -r '.cwd // "unknown"' 2>/dev/null || echo "unknown")
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# Append to log
echo "{\"skill\":\"$SKILL_NAME\",\"timestamp\":\"$TIMESTAMP\",\"session_id\":\"$SESSION_ID\",\"project\":\"$PROJECT_DIR\"}" >> "$LOG_FILE"

exit 0
