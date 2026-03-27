#!/usr/bin/env bash
# Auto-detect new projects and surface skill recommendations.
#
# Fires on SessionStart. Checks if this project has been scanned before.
# If not, runs gap_analysis.py in the background and injects a context
# message telling Claude to surface recommendations to the user.
#
# State: ~/.claude/skill-lifecycle-scanned-projects.json
# Format: {"projects": {"/path/to/project": {"scanned_at": "ISO", "skills_recommended": 5}}}

set -euo pipefail

HOOK_INPUT=$(cat)
PROJECT_DIR=$(echo "$HOOK_INPUT" | jq -r '.cwd // empty' 2>/dev/null || pwd)

# Skip if no project dir or if it's the home directory
if [[ -z "$PROJECT_DIR" || "$PROJECT_DIR" == "$HOME" || "$PROJECT_DIR" == "/" ]]; then
  exit 0
fi

SCANNED_FILE="$HOME/.claude/skill-lifecycle-scanned-projects.json"
LIFECYCLE_SCRIPTS="$(find "$HOME/.claude/skills/skill-lifecycle/scripts" ".claude/skills/skill-lifecycle/scripts" -name lifecycle_state.py -print -quit 2>/dev/null || true)"

# If framework isn't installed, skip silently
if [[ -z "$LIFECYCLE_SCRIPTS" ]]; then
  exit 0
fi

SCRIPTS_DIR="$(dirname "$LIFECYCLE_SCRIPTS")"

# Initialize scanned-projects file if missing
if [[ ! -f "$SCANNED_FILE" ]]; then
  echo '{"projects":{}}' > "$SCANNED_FILE"
fi

# Check if this project has been scanned
ALREADY_SCANNED=$(jq -r --arg p "$PROJECT_DIR" '.projects[$p] // empty' "$SCANNED_FILE" 2>/dev/null)

if [[ -n "$ALREADY_SCANNED" ]]; then
  # Already scanned — don't nag. Just exit silently.
  exit 0
fi

# --- New project detected! ---

# Detect project type quickly (no expensive scans)
PROJECT_SIGNALS=""
[[ -f "$PROJECT_DIR/package.json" ]]    && PROJECT_SIGNALS="${PROJECT_SIGNALS}node "
[[ -f "$PROJECT_DIR/pyproject.toml" || -f "$PROJECT_DIR/requirements.txt" || -f "$PROJECT_DIR/setup.py" ]] && PROJECT_SIGNALS="${PROJECT_SIGNALS}python "
[[ -f "$PROJECT_DIR/go.mod" ]]          && PROJECT_SIGNALS="${PROJECT_SIGNALS}go "
[[ -f "$PROJECT_DIR/Cargo.toml" ]]      && PROJECT_SIGNALS="${PROJECT_SIGNALS}rust "
[[ -f "$PROJECT_DIR/Makefile" ]]        && PROJECT_SIGNALS="${PROJECT_SIGNALS}make "
[[ -d "$PROJECT_DIR/terraform" || -f "$PROJECT_DIR/main.tf" ]] && PROJECT_SIGNALS="${PROJECT_SIGNALS}terraform "
[[ -d "$PROJECT_DIR/ansible" ]]         && PROJECT_SIGNALS="${PROJECT_SIGNALS}ansible "
[[ -f "$PROJECT_DIR/Dockerfile" || -f "$PROJECT_DIR/docker-compose.yml" ]] && PROJECT_SIGNALS="${PROJECT_SIGNALS}docker "
[[ -d "$PROJECT_DIR/.github/workflows" ]] && PROJECT_SIGNALS="${PROJECT_SIGNALS}github-actions "

# If no signals at all, probably not a real project — skip
if [[ -z "$PROJECT_SIGNALS" ]]; then
  exit 0
fi

# Mark as scanned (even before analysis — prevents re-firing)
TEMP=$(mktemp)
jq --arg p "$PROJECT_DIR" --arg t "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  '.projects[$p] = {"scanned_at": $t, "skills_recommended": 0, "status": "pending"}' \
  "$SCANNED_FILE" > "$TEMP" && mv "$TEMP" "$SCANNED_FILE"

# Count installed skills
SKILL_COUNT=$(find "$HOME/.claude/skills" ".claude/skills" -name "SKILL.md" 2>/dev/null | wc -l || echo "0")

# Inject context telling Claude about the new project
cat << EOF
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "NEW PROJECT DETECTED: This is the first Claude Code session in ${PROJECT_DIR}. Detected stack: ${PROJECT_SIGNALS}. The user has ${SKILL_COUNT} skills installed. The skill-lifecycle framework suggests running /skill-lifecycle research to discover what skills would help in this project. Mention this to the user early in the conversation — something like: 'I notice this is a new project (${PROJECT_SIGNALS}). I can scan it and recommend skills that would help — want me to run /skill-lifecycle research?' Do NOT run it automatically. Just suggest it once, naturally, when there's a pause in the conversation."
  }
}
EOF

exit 0
