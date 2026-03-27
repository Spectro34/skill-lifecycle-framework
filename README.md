# Skill Lifecycle Framework

Automatically discovers what Claude Code skills your project needs, recommends them, tracks which ones actually get used, and flags the ones that don't work.

## 30-Second Setup

```bash
git clone https://github.com/Spectro34/skill-lifecycle-framework.git
cd skill-lifecycle-framework
bash install.sh
```

That's it. Close this terminal. From now on, **every project you open with Claude Code** has the framework active.

## What Happens Next

### First time you open any project:

```
$ cd ~/my-react-app
$ claude

Claude: "I notice this is a new project (node, docker, github-actions).
        Want me to scan it and recommend skills? /skill-lifecycle research"
```

The framework detected your stack automatically. Say yes:

```
> /skill-lifecycle research
```

It scans your project — package.json, git history, CI/CD, Makefile, tests — and cross-references against:
- Skills you already have installed
- Your actual usage history (what do you do most?)

```
| # | Skill              | Priority | Why                                    |
|---|--------------------|----------|----------------------------------------|
| 1 | test-runner        | High     | 43 test commits, no test automation    |
| 2 | docker-compose-dev | Medium   | docker-compose.yml present, no helpers |
| 3 | pr-review          | High     | Active PR workflow                     |
|   |                    |          | → Already installed (plugin)           |

2 new skills recommended. Want me to build them?
```

### After skills have been running for a while:

```
> /skill-lifecycle monitor

| Skill              | Usage    | Trigger F1 | Quality | Action       |
|--------------------|----------|------------|---------|--------------|
| test-runner        | Active   | 0.91       | +28%    | Keep         |
| docker-compose-dev | Never    | 0.42       | +3%     | Fix or remove|
```

The framework knows docker-compose-dev never fired (real data from the usage tracker, not guessing) and its trigger accuracy is bad. Fix it or remove it:

```
> /skill-lifecycle churn

"docker-compose-dev: F1=0.42, never used. Fix description or remove?"

> fix it

Running description optimizer... 5 iterations... F1 improved to 0.79.
"Keep monitoring or remove?"
```

## How It Works (Under the Hood)

**Two hooks fire automatically:**

1. **SessionStart** — When you open any project, checks if it's been scanned before. If not, suggests a scan.
2. **PostToolUse** — Every time a skill fires, silently logs it to `~/.claude/skill-invocation-log.jsonl`. Zero overhead (async).

**Four skills do the work:**

| Skill | What it does |
|-------|-------------|
| `/skill-lifecycle` | Orchestrates everything — routes to the right phase |
| `/evaluate-skills` | Scans a project and recommends what to build |
| `/skill-evaluator` | Audits installed skills (usage, trigger accuracy, quality) |
| `/skill-creator` | Builds, tests, and optimizes skills |

**No skills are built automatically.** The framework recommends and you decide.

## Commands

```
/skill-lifecycle research     → Scan project, recommend skills
/skill-lifecycle monitor      → Audit all installed skills
/skill-lifecycle churn        → Fix or remove underperformers
/skill-lifecycle status       → What's tracked, what's healthy
```

## What Gets Installed

```
~/.claude/
├── skills/
│   ├── skill-lifecycle/          # Orchestrator + scripts + agents
│   ├── evaluate-skills/          # Project scanner
│   ├── skill-evaluator/          # Audit engine
│   └── skill-creator/            # Skill builder (fork)
├── hooks/
│   ├── on-project-open.sh        # New project detection
│   └── log-skill-usage.sh        # Usage tracking
└── settings.json                 # Hook wiring (merged, not overwritten)
```

## Uninstall

```bash
cd skill-lifecycle-framework
bash uninstall.sh
```

Removes skills, hooks, and settings entries. Your other Claude Code configuration is preserved.

## Requirements

- Claude Code (CLI, desktop, or IDE extension)
- Python 3.8+
- `jq` (for hooks — usually pre-installed)

## Customization

All thresholds are in `~/.claude/skills/skill-lifecycle/references/thresholds.md`:

| Setting | Default | What it controls |
|---------|---------|-----------------|
| F1 pass threshold | 0.80 | Skills below this get flagged |
| Quality delta minimum | 5% | Skills with less improvement get flagged |
| Dormant days | 30 | Unused skills get flagged after this |
| Declining trend window | 3 audits | Consecutive F1 drops trigger investigation |

## License

MIT
