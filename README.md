# Skill Lifecycle Framework

A self-contained Claude Code framework that manages the full lifecycle of AI skills: **discover** what's needed, **build** them, **test** in sandbox, **deploy**, **monitor** effectiveness, and **churn** underperformers.

## What This Is

When you work with Claude Code, skills are reusable expertise modules that make the AI better at specific tasks. But managing them is manual — you have to figure out what skills you need, create them one by one, hope they trigger correctly, and manually clean up the ones that don't work.

This framework automates the entire process with four interconnected skills:

```
/evaluate-skills  →  /skill-creator  →  /skill-evaluator
        ↑                                       │
        └──────── /skill-lifecycle ─────────────┘
                  (orchestrates everything)
```

## Getting Started

### Clone and use immediately

```bash
git clone <this-repo> my-project
cd my-project
claude  # Skills auto-load from .claude/
```

That's it. The `.claude/skills/` directory is auto-discovered by Claude Code on session start.

### Or install into an existing project

```bash
# Copy .claude/skills/ into your project
cp -r path/to/this-repo/.claude/skills/ your-project/.claude/skills/
```

## Usage

### Full lifecycle (recommended)

```bash
/skill-lifecycle              # Start from scratch or resume
/skill-lifecycle research     # What skills does my project need?
/skill-lifecycle build        # Create the recommended skills
/skill-lifecycle test         # Sandbox test before deploying
/skill-lifecycle deploy       # Optimize and finalize
/skill-lifecycle monitor      # Audit effectiveness
/skill-lifecycle churn        # Remove underperformers
/skill-lifecycle status       # Where am I?
```

### Individual skills

```bash
/evaluate-skills              # Just scan and recommend
/skill-creator                # Just build one skill
/skill-evaluator              # Just audit what's installed
```

## How It Works

### 1. Research Phase
Scans your project (languages, frameworks, git history, CI/CD, MCP servers) and cross-references against installed skills and your usage history to find gaps.

### 2. Build Phase
Hands off to the skill-creator with full project context — no re-interviewing. Builds skills one at a time with user feedback.

### 3. Test Phase (Sandbox)
Runs each skill through isolated `claude -p` subprocesses:
- **Trigger accuracy**: Does it fire when it should? (F1 scoring)
- **Quality impact**: Is the output actually better with the skill? (with/without comparison)

### 4. Deploy Phase
Optimizes trigger descriptions using a train/test evaluation loop to prevent overfitting.

### 5. Monitor Phase
Mines session history for real usage data, re-tests trigger accuracy, measures quality over time.

### 6. Churn Phase
Decision engine applies rules:
- F1 < 0.50 → fix description automatically
- Quality delta < 5% → rewrite or remove
- Dormant 30+ days → review for removal
- F1 declining across audits → investigate

**Skills are archived, never deleted.** Every removal requires user confirmation.

## Project Structure

```
.claude/
├── skills/
│   ├── skill-lifecycle/          # The orchestrator
│   │   ├── SKILL.md
│   │   ├── scripts/
│   │   │   ├── lifecycle_state.py    # State machine
│   │   │   ├── gap_analysis.py       # Recommendation cross-referencing
│   │   │   ├── churn_decision.py     # Keep/fix/remove engine
│   │   │   └── history_analyzer.py   # Usage mining (standalone)
│   │   ├── agents/
│   │   │   ├── test-agent.md         # Sandbox test executor
│   │   │   └── monitor-agent.md      # Quick health checker
│   │   └── references/
│   │       └── thresholds.md         # All tunable numbers
│   │
│   ├── evaluate-skills/              # Project scanner + recommender
│   │   └── SKILL.md
│   │
│   ├── skill-evaluator/              # Audit engine
│   │   └── SKILL.md
│   │
│   └── skill-creator/                # Forked skill builder + eval infrastructure
│       ├── SKILL.md
│       ├── scripts/                  # run_eval.py, run_loop.py, aggregate_benchmark.py, etc.
│       ├── agents/                   # grader.md, comparator.md, analyzer.md
│       ├── eval-viewer/              # generate_review.py + viewer.html
│       ├── assets/                   # eval_review.html template
│       └── references/               # schemas.md
```

## Requirements

- **Claude Code** (CLI, desktop app, or IDE extension)
- **Python 3.8+** (for evaluation scripts — stdlib only, no pip installs)

## Customization

All thresholds are in `.claude/skills/skill-lifecycle/references/thresholds.md`:
- Test pass/fail criteria (F1, quality delta, token overhead)
- Churn decision thresholds (dormancy days, declining trend window)
- Sandbox parameters (workers, timeout, runs per query)

## License

MIT — see skill-creator's LICENSE.txt for Anthropic's original skill-creator license.
