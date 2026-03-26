# Skill Lifecycle Framework

This project is a self-contained Claude Code skill management framework. All skills, agents, scripts, and configuration live in `.claude/` and auto-load when you open this project with Claude Code.

## Available Skills

| Skill | Command | What it does |
|-------|---------|-------------|
| skill-lifecycle | `/skill-lifecycle` | Full lifecycle orchestrator: research → build → test → deploy → monitor → churn |
| evaluate-skills | `/evaluate-skills` | Scan a project and recommend skills to create |
| skill-evaluator | `/skill-evaluator` | Audit installed skills for usage, trigger accuracy, quality |
| skill-creator | `/skill-creator` | Create, test, iterate, and optimize skills |

## Quick Start

```bash
/skill-lifecycle status       # Check state
/skill-lifecycle research     # Discover what skills you need
/skill-lifecycle monitor      # Audit existing skills
/skill-lifecycle churn        # Clean up underperformers
```

## Project Structure

- `.claude/skills/` — All four skills with their scripts, agents, and references
- `.claude/skill-lifecycle-state.json` — Persistent state (auto-created, gitignored)
- The skill-creator fork includes: run_eval.py, run_loop.py, aggregate_benchmark.py, grader/comparator/analyzer agents, eval-viewer

## Dependencies

- Python 3.8+ (for scripts)
- `claude` CLI (for `run_eval.py` sandbox testing via `claude -p`)
- No external Python packages required (stdlib only)
