---
name: skill-lifecycle
description: >
  Manage the full lifecycle of Claude Code skills: discover what's needed, build them,
  test in sandbox, deploy, monitor effectiveness, and churn underperformers. Use this
  skill whenever the user wants to evaluate which skills to create, audit and improve
  their skill library, run a skill health check, clean up unused skills, bootstrap
  skills for a new project, or manage skills end-to-end. Also trigger when the user
  says things like "what skills do I need", "clean up my skills", "are my skills working",
  "skill audit", "skill maintenance", "optimize my skills", "remove bad skills",
  "skill health", or "manage my skills". Even if the user only mentions one phase
  (like "test my skills" or "monitor skills"), use this skill to route to the right phase.
user-invocable: true
argument-hint: "[research|build|test|deploy|monitor|churn|status] [--auto] [--skill name]"
allowed-tools: Read, Glob, Grep, Bash, Agent, Write, Skill
---

# Skill Lifecycle Orchestrator

You are a lifecycle manager for Claude Code skills. You coordinate three existing skills — `evaluate-skills`, `skill-creator`, and `skill-evaluator` — into a unified pipeline that takes skills from idea to production and churns the ones that don't work.

You are a **thin orchestrator**: never duplicate logic that exists in the three downstream skills. Your job is to invoke them in the right order, pass context between them, manage state, and make phase-transition decisions.

## Quick Reference

```
/skill-lifecycle                → Resume from current state, or start RESEARCH
/skill-lifecycle research       → Discover what skills are needed
/skill-lifecycle build          → Create skills from prior research
/skill-lifecycle test           → Sandbox test skills in TESTING state
/skill-lifecycle deploy         → Finalize and optimize tested skills
/skill-lifecycle monitor        → Audit all installed skills
/skill-lifecycle churn          → Remove/rebuild underperformers
/skill-lifecycle status         → Show current state
/skill-lifecycle --auto         → Full pipeline, only pause for removals
/skill-lifecycle --skill <name> → Focus on one skill
```

## State Management

All state lives in `.claude/skill-lifecycle-state.json` (project-scoped). Read it at the start of every invocation. If it doesn't exist, initialize it.

To manage state, run the `lifecycle_state.py` script in this skill's `scripts/` directory:

```bash
# Find scripts in project scope first, fall back to user scope
LIFECYCLE_SCRIPTS="$(dirname "$(find .claude/skills/skill-lifecycle/scripts ~/.claude/skills/skill-lifecycle/scripts -name lifecycle_state.py -print -quit 2>/dev/null)")"

# Read current state
python3 "$LIFECYCLE_SCRIPTS/lifecycle_state.py" status

# Add a skill to tracking
python3 "$LIFECYCLE_SCRIPTS/lifecycle_state.py" add --name "skill-name" --phase RECOMMENDED

# Transition a skill's phase
python3 "$LIFECYCLE_SCRIPTS/lifecycle_state.py" transition --name "skill-name" --to BUILDING

# List skills in a specific phase
python3 "$LIFECYCLE_SCRIPTS/lifecycle_state.py" list --phase TESTING
```

Per-skill phase transitions:
```
RECOMMENDED → BUILDING → TESTING → DEPLOYED → MONITORING
                  ↑                              │
                  └──── REBUILDING ◄─────────────┘
                                                 │
                                            CHURNED (terminal)
```

---

## Phase 1: RESEARCH

**Goal**: Discover what skills the user needs but doesn't have.

### Steps

1. **Invoke `/evaluate-skills`** via the Skill tool. This runs the full project scan and produces recommendations with an `<!-- EVALUATE-SKILLS-OUTPUT -->` block.

2. **Run gap analysis**. First, extract the recommendations from the evaluate-skills output into a JSON array. Each item needs: `name`, `priority`, `type`, `why`, `steps`, `tools`. Save it to a temp file, then pipe it in:
   ```bash
   # Write the recommendations JSON array to a temp file
   cat > /tmp/skill-recs.json << 'RECS_EOF'
   [
     {"name": "skill-name", "priority": "High", "type": "Task automation", "why": "reason from evaluate-skills", "steps": "step1, step2", "tools": "tool1, tool2"},
     ...
   ]
   RECS_EOF

   # Pipe into gap analysis
   cat /tmp/skill-recs.json | python3 "$LIFECYCLE_SCRIPTS/gap_analysis.py" \
     --skills-dirs ~/.claude/skills .claude/skills \
     --plugins-dir ~/.claude/plugins/marketplaces \
     --history ~/.claude/history.jsonl
   ```
   This cross-references recommendations against installed skills (deduplicates) and user behavior in history.jsonl (re-ranks by activity match). It outputs a JSON gap report to stdout.

3. **Present the enriched gap table** to the user:
   ```
   | # | Skill | Priority | Why | Already Have? | User Activity Match |
   ```

4. **USER GATE**: Ask which skills to build. Store selections in state via `lifecycle_state.py add`.

### When to skip
If the user already knows what they want to build (e.g., "build me an ansible-deploy skill"), skip research and go directly to BUILD. Add the skill to state as RECOMMENDED, then immediately transition to BUILDING.

---

## Phase 2: BUILD

**Goal**: Create each approved skill via skill-creator.

### Steps

For each skill in RECOMMENDED state (one at a time):

1. Transition to BUILDING: `python3 "$LIFECYCLE_SCRIPTS/lifecycle_state.py" transition --name <name> --to BUILDING`

2. **Invoke `/skill-creator`** via the Skill tool. The skill-creator will auto-detect the evaluate-skills output in conversation context and skip its interview phase (it has a "Coming from evaluate-skills" flow). If coming from a CHURN/REBUILD, it detects the health report context instead ("Coming from skill-evaluator" flow).

3. The skill-creator takes over the conversation for this skill. It runs its full loop: draft SKILL.md → generate test cases → run evals → iterate with user feedback.

4. When the user indicates the skill is done, transition to TESTING: `python3 "$LIFECYCLE_SCRIPTS/lifecycle_state.py" transition --name <name> --to TESTING`

5. Move to the next skill, or proceed to TEST phase if all skills are built.

### Important
- Build skills **sequentially** — each needs user interaction
- Don't rush the user; the skill-creator has its own pace

---

## Phase 3: TEST (Sandbox)

**Goal**: Verify skills work in isolated `claude -p` subprocesses before deploying.

### Locate skill-creator scripts
```bash
SKILL_CREATOR_PATH=$(find .claude/skills/skill-creator ~/.claude/plugins -path "*/skill-creator" -type d 2>/dev/null | head -1)
```

### Steps

For each skill in TESTING state:

1. **Trigger accuracy test** — Check if the skill fires when it should:
   ```bash
   cd "$SKILL_CREATOR_PATH" && python -m scripts.run_eval \
     --eval-set <workspace>/evals/trigger_eval.json \
     --skill-path ~/.claude/skills/<name> \
     --runs-per-query 2 --verbose
   ```
   If the skill-creator already ran trigger evals during build, check the workspace for existing results and reuse them.

2. **Quality impact test** — Spawn parallel subagents:
   - **With-skill agent**: Execute a test prompt with the skill loaded. Use the `agents/test-agent.md` instructions from this skill's directory.
   - **Without-skill agent**: Same prompt, no skill.
   - Grade both via the skill-creator's grader agent (`$SKILL_CREATOR_PATH/agents/grader.md`)
   - Aggregate: `cd "$SKILL_CREATOR_PATH" && python -m scripts.aggregate_benchmark <workspace>`

3. **Score and decide** — Read `references/thresholds.md` for exact numbers:
   - **PASS** (F1 >= 0.80 AND quality delta >= +15%): Auto-advance to DEPLOY
   - **MARGINAL** (F1 0.50-0.80 OR delta 5-15%): Present results, ask user
   - **FAIL** (F1 < 0.50 OR delta < 5%): Offer to iterate with skill-creator or discard

4. Present results:
   ```
   | Skill | Trigger F1 | Quality Delta | Token Overhead | Verdict |
   ```

5. **USER GATE** (marginal/failed only): iterate, keep anyway, or discard.

6. Update state for passing/kept skills: transition to DEPLOYED.

### The sandbox model
`run_eval.py` creates temp files in `.claude/commands/`, runs `claude -p` as isolated subprocesses, and cleans up after. Each test is fully isolated — no effect on the main session.

---

## Phase 4: DEPLOY

**Goal**: Finalize tested skills and optimize their trigger descriptions.

### Steps

1. Skills already live in `~/.claude/skills/<name>/` from the build phase. No file movement needed.

2. **Description optimization** (offer to the user, run in background if they agree):
   ```bash
   cd "$SKILL_CREATOR_PATH" && python -m scripts.run_loop \
     --eval-set <workspace>/evals/trigger_eval.json \
     --skill-path ~/.claude/skills/<name> \
     --model <current-model-id> \
     --max-iterations 5 --verbose
   ```
   Apply the `best_description` from the JSON output to the skill's SKILL.md frontmatter.

3. **Optional packaging** (if user wants to share):
   ```bash
   cd "$SKILL_CREATOR_PATH" && python -m scripts.package_skill ~/.claude/skills/<name>
   ```

4. Update state: transition to DEPLOYED with timestamp.

5. Report: "Deployed N skills. Description optimization improved trigger accuracy by X%."

---

## Phase 5: MONITOR

**Goal**: Audit all installed skills for real-world effectiveness.

### Steps

1. **Invoke `/skill-evaluator`** via the Skill tool. This runs the full audit: usage analysis (history.jsonl mining), trigger accuracy testing, and quality impact measurement. It produces a Skill Health Report.

2. **Update state** for each tracked skill:
   - Set `last_audit` timestamp
   - Append metrics to `audit_history`
   - Update current F1, quality delta, usage status

3. **Run churn decision engine**:
   ```bash
   python3 "$LIFECYCLE_SCRIPTS/churn_decision.py" \
     --state ~/.claude/skill-lifecycle-state.json
   ```
   This reads the latest audit data and applies the decision tree. Outputs a JSON actions list.

4. **Present monitoring summary**:
   ```
   ## Skill Health Summary
   | Skill | Usage | Trigger F1 | Quality Delta | Status | Action Needed |

   ## Churn Candidates
   - /skill-name: [reason] → [recommended action]
   ```

5. If churn candidates exist, ask: "Want me to proceed with the churn phase?"

---

## Phase 6: CHURN

**Goal**: Remove or rebuild underperforming skills.

### Decision Tree (from `scripts/churn_decision.py`)

| Condition | Action |
|-----------|--------|
| trigger_f1 < 0.50 | FIX_DESCRIPTION → run `run_loop.py`. If still < 0.50 → REWRITE_OR_REMOVE |
| quality_delta < 5% | REWRITE_OR_REMOVE |
| Not used in 30+ days | REVIEW_FOR_REMOVAL |
| F1 declining across 3+ audits | INVESTIGATE (possible model changes) |

### Steps

1. For **FIX_DESCRIPTION** actions:
   - Run `run_loop.py` to optimize the description
   - Re-test trigger accuracy
   - If fixed (F1 >= 0.50): update state, done
   - If still broken: escalate to REWRITE_OR_REMOVE

2. For **REWRITE_OR_REMOVE** actions:
   - Present to user: "This skill [reason]. Rewrite or remove?"
   - **Rewrite**: Transition to REBUILDING, invoke skill-creator with health report context
   - **Remove**: Proceed to archival

3. For **REVIEW_FOR_REMOVAL** actions:
   - Present to user: "This skill hasn't been used in N days."
   - Check if it's a passive (auto-triggered) skill vs user-invoked
   - User decides: keep, remove, or re-test

4. **USER GATE**: Every removal requires explicit confirmation:
   ```
   Skills to remove:
   - /old-deploy (never used, F1=0.28, no quality improvement)
   - /format-csv (dormant 45 days)

   Confirm removal? [list numbers to remove, or 'none']
   ```

5. For confirmed removals:
   ```bash
   # Archive, never hard delete
   mkdir -p ~/.claude/skill-lifecycle-archive
   mv ~/.claude/skills/<name> ~/.claude/skill-lifecycle-archive/<name>-$(date +%Y%m%d)
   ```
   Update state: mark as CHURNED with reason and timestamp.

6. For skills marked for rebuild: transition to REBUILDING → follow BUILD phase.

---

## Argument Routing

Parse `$ARGUMENTS` at the start:

- **No arguments or empty**: Load state. If IDLE → start RESEARCH. If mid-pipeline → resume from current phase.
- **`research`**: Start/restart RESEARCH phase.
- **`build`**: Go to BUILD. Requires prior research in state (skills in RECOMMENDED).
- **`test`**: Go to TEST. Requires skills in TESTING state.
- **`deploy`**: Go to DEPLOY. Requires tested skills.
- **`monitor`** or **`audit`**: Go to MONITOR.
- **`churn`**: Go to CHURN. Requires churn candidates from last audit.
- **`status`**: Print current state summary and exit:
  ```
  ## Skill Lifecycle Status
  State: [current orchestrator phase]
  Last run: [timestamp]

  | Skill | Phase | Last Audit | F1 | Quality Delta |
  ```
- **`--auto`**: Run RESEARCH → BUILD → TEST → DEPLOY without pausing, except for USER GATEs on skill selection and removals.
- **`--skill <name>`**: Focus all operations on a single skill.

---

## Integration Points

| Downstream | How invoked | Context passed |
|------------|-------------|----------------|
| `/evaluate-skills` | Skill tool | Project path from cwd |
| `/skill-creator` | Skill tool | evaluate-skills output in conversation (auto-detected) OR health report in conversation |
| `/skill-evaluator` | Skill tool | Optional `--skill <name>` argument |
| `run_eval.py` | Bash (cd to skill-creator dir) | `--eval-set`, `--skill-path` flags |
| `run_loop.py` | Bash (cd to skill-creator dir) | `--eval-set`, `--skill-path`, `--model` flags |
| `aggregate_benchmark.py` | Bash (cd to skill-creator dir) | workspace path argument |
| `package_skill.py` | Bash (cd to skill-creator dir) | skill path argument |

---

## Autonomy Rules

| Action | Autonomous | Needs user approval |
|--------|-----------|-------------------|
| Project scan, gap analysis | Yes | No |
| Which skills to build | No | **Yes** |
| Skill creation (via skill-creator) | Partial | **Yes** (skill-creator has its own loop) |
| Sandbox testing | Yes | No |
| Deploy passing skills | Yes | No |
| Description optimization | Yes | No |
| Audit/monitoring | Yes | No |
| Remove skills | No | **Always** |
| Rebuild skills | No | **Yes** |

Never delete a skill without user confirmation. Never skip a USER GATE even in `--auto` mode (auto mode skips research-to-build-to-test-to-deploy gates, but still requires confirmation for skill selection and removals).
