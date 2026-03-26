---
name: skill-evaluator
description: Audit and measure the real-world effectiveness of installed Claude Code skills. Tracks which skills actually get triggered, measures output quality with/without each skill, tests triggering accuracy (false positives/negatives), and generates a health report ranking skills by usefulness. Use this skill whenever the user wants to evaluate skills, audit skill performance, find unused or broken skills, check if skills are triggering correctly, compare skill versions, or clean up their skill library. Works for both interactive sessions and remote/scheduled agents.
user-invocable: true
argument-hint: "[skill-name] [--full] [--triggers-only] [--quality-only] [--usage-only]"
allowed-tools: Read, Glob, Grep, Bash, Agent, Write
---

# Skill Evaluator

You are a skill auditing and measurement engine. Your job is to evaluate the real-world usefulness of the user's installed Claude Code skills across three dimensions: **usage**, **triggering accuracy**, and **output quality**.

## Overview

The evaluation produces a **Skill Health Report** covering:

1. **Usage Analysis** — Which skills actually fire in real sessions? Which are dead weight?
2. **Trigger Accuracy** — Do skills fire when they should? Do they stay quiet when they shouldn't?
3. **Quality Impact** — When a skill fires, does it actually improve the output vs. no skill?

Each dimension can be run independently or together. A full audit runs all three.

## Step 0: Discover All Skills

Before anything else, inventory every skill available to the user:

```
Scan locations:
- ~/.claude/skills/*/SKILL.md              (user skills)
- ~/.claude/plugins/marketplaces/**/skills/*/SKILL.md  (plugin skills)
- .claude/skills/*/SKILL.md                (project-local skills)
```

For each skill found, parse the YAML frontmatter to extract:
- `name`
- `description`
- `user-invocable` (true/false)
- `allowed-tools`

Build a skill inventory table and show it to the user before proceeding. If the user passed a specific skill name as an argument, focus the evaluation on just that skill.

---

## Step 1: Usage Analysis

The goal is to understand which skills actually get used in practice.

### Session History Mining

Read `~/.claude/history.jsonl` — this contains every session's prompts with timestamps and project paths.

For each skill in the inventory:
1. Search the history for mentions of `/skill-name` (direct invocations)
2. Search for keywords from the skill's description that would indicate the skill *should* have been useful
3. Cross-reference with session metadata in `~/.claude/sessions/` to understand the context

Produce a usage summary:

| Skill | Direct Invocations | Likely Relevant Sessions | Last Used | Status |
|-------|-------------------|------------------------|-----------|--------|
| /name | count | count | date | Active / Dormant / Never Used |

**Dormant** = not used in the last 30 days but was used before.
**Never Used** = no evidence of invocation or relevant sessions ever.

### Missed Opportunity Detection

This is the most valuable part. For each session where a skill *wasn't* invoked but the user's prompt matched the skill's description keywords:
- Flag it as a **missed opportunity**
- This suggests the skill's description needs improvement (undertriggering)

Report the top missed opportunities per skill.

### Remote Agent / Trigger Analysis

Check for scheduled trigger history:
- Look for trigger execution logs or output files
- Check `~/.claude/` for any remote agent state
- If the user has the `schedule` skill configured, check its artifacts

For remote agents, track:
- How often each trigger runs
- Whether skills are being leveraged in trigger prompts
- Success/failure rates

---

## Step 2: Trigger Accuracy Testing

This tests whether each skill's description causes it to fire at the right times.

### Generate Test Queries

For each skill being evaluated, generate 16 test queries:
- **8 should-trigger**: Realistic prompts where this skill would genuinely help. Vary phrasing — formal, casual, verbose, terse. Include edge cases where the user doesn't name the skill explicitly but clearly needs it.
- **8 should-not-trigger**: Near-miss prompts that share keywords but need something different. These should be genuinely tricky, not obviously irrelevant.

The queries must be realistic and specific — include file paths, personal context, column names, casual speech, typos. Not abstract requests.

Save as `trigger_eval.json`:
```json
[
  {"query": "realistic user prompt here", "should_trigger": true},
  {"query": "tricky near-miss prompt", "should_trigger": false}
]
```

### Run Trigger Evaluation

Use the skill-creator's evaluation infrastructure. The key script is:

```bash
SKILL_CREATOR_PATH=$(find ~/.claude/plugins -path "*/skill-creator/skills/skill-creator" -type d 2>/dev/null | head -1)
```

Then run the evaluation:

```bash
python -m scripts.run_eval \
  --eval-set <path-to-trigger-eval.json> \
  --skill-path <path-to-skill> \
  --model <current-model-id> \
  --runs-per-query 2 \
  --verbose
```

Run this from the skill-creator's directory so the scripts module resolves correctly. If `run_eval.py` is not available, fall back to manual testing: spawn subagents with `claude -p` for each query and check if the skill was invoked.

### Score Each Skill

Calculate:
- **True Positive Rate** (TPR): % of should-trigger queries that did trigger
- **True Negative Rate** (TNR): % of should-not-trigger queries that didn't trigger
- **F1 Score**: Harmonic mean of precision and recall
- **Accuracy**: Overall correct decisions / total queries

| Skill | TPR | TNR | F1 | Accuracy | Verdict |
|-------|-----|-----|-----|----------|---------|
| /name | 87% | 93% | 0.90 | 90% | Good / Needs Work / Broken |

**Verdicts:**
- **Good**: F1 >= 0.80
- **Needs Work**: F1 between 0.50 and 0.80
- **Broken**: F1 < 0.50

For skills rated "Needs Work" or "Broken", note specifically which queries failed and why — the user will need this to fix the description.

---

## Step 3: Quality Impact Measurement

This is the most expensive step but also the most informative. It answers: "Does this skill actually make the output better?"

### Design Quality Evals

For each skill, create 3 representative test prompts — tasks that are squarely in the skill's domain. These should be complex enough that a skill would genuinely help (simple one-step tasks won't differentiate).

For each prompt, define 3-5 **expectations** — objectively verifiable statements about what good output looks like:
- "The output contains a summary table"
- "All file paths referenced actually exist"
- "The suggested command runs without error"

### Run With/Without Comparisons

For each test prompt, spawn two subagents in parallel:

**With-skill run:**
```
Execute this task with the skill at <skill-path> available:
Task: <prompt>
Save all outputs to: <workspace>/quality/skill-name/eval-N/with_skill/outputs/
```

**Without-skill run (baseline):**
```
Execute this task WITHOUT any special skills:
Task: <prompt>
Save all outputs to: <workspace>/quality/skill-name/eval-N/without_skill/outputs/
```

### Grade Results

For each run, evaluate the expectations. Use programmatic checks where possible (file existence, command execution, content matching), fall back to LLM grading for subjective criteria.

Produce a quality delta per skill:

| Skill | With Skill Pass Rate | Baseline Pass Rate | Delta | Tokens (With) | Tokens (Without) | Worth It? |
|-------|---------------------|-------------------|-------|---------------|------------------|-----------|
| /name | 87% | 60% | +27% | 15k | 12k | Yes |

**Worth It?** considers both the quality delta AND the token cost:
- **Yes**: Quality improved by >= 15% with reasonable token overhead (< 2x)
- **Marginal**: Quality improved by 5-15% or token cost > 2x baseline
- **No**: Quality didn't improve or got worse

---

## Step 4: Generate the Skill Health Report

Combine all findings into a single report. Save to `<workspace>/skill-health-report.md`.

### Report Structure

```markdown
# Skill Health Report
Generated: [date]
Skills Evaluated: [count]
Evaluation Scope: [Usage / Triggers / Quality / Full]

## Executive Summary
[2-3 sentences: how many skills are healthy, how many need attention, top recommendation]

## Skill Rankings

| Rank | Skill | Usage | Trigger F1 | Quality Delta | Overall | Action |
|------|-------|-------|-----------|---------------|---------|--------|
| 1 | /name | Active | 0.92 | +30% | Excellent | Keep |
| 2 | /name | Active | 0.75 | +15% | Good | Tune description |
| ... | | | | | | |
| N | /name | Never | 0.30 | -5% | Poor | Remove or rewrite |

## Detailed Findings

### /skill-name
**Status:** [Excellent / Good / Needs Work / Remove]
**Usage:** [Active / Dormant / Never Used] — [N] invocations, last used [date]
**Triggering:** F1 [score] — [specific failures noted]
**Quality:** [+/-N%] delta — [what improved, what didn't]
**Recommendation:** [specific action to take]
**Missed Opportunities:** [N] sessions where this skill could have helped but didn't fire

[repeat for each skill]

## Recommendations
1. [Highest priority action]
2. [Second priority]
3. ...

## Skills to Remove
[List any skills that are dead weight — never used, bad trigger accuracy, no quality improvement]
```

### Present to the User

After generating the report, present the executive summary and rankings table directly in conversation. Tell the user where the full report is saved. Then ask:

"Would you like me to:
1. **Fix descriptions** for skills with poor trigger accuracy (using the skill-creator's description optimizer)?
2. **Remove** skills that aren't providing value?
3. **Deep-dive** into a specific skill's results?
4. **Create new skills** to fill gaps found in the usage analysis (missed opportunities)?"

If the user wants to fix descriptions, invoke the skill-creator's `run_loop.py` description optimizer. If they want to create new skills to fill gaps, hand off to the skill-creator with the gap analysis as context.

---

## Handling Arguments

- **No arguments**: Run a full audit on all skills
- **`skill-name`**: Evaluate only that skill (all three dimensions)
- **`--full`**: Full audit, all skills, all dimensions (same as no args)
- **`--triggers-only`**: Skip usage and quality, just test trigger accuracy
- **`--quality-only`**: Skip usage and triggers, just measure quality impact
- **`--usage-only`**: Skip triggers and quality, just analyze usage patterns
- Multiple flags can combine: `--triggers-only --usage-only` runs both but skips quality

## Workspace

All evaluation artifacts go into `skill-evaluator-workspace/` in the current directory:

```
skill-evaluator-workspace/
├── skill-health-report.md
├── inventory.json
├── usage/
│   ├── history-analysis.json
│   └── missed-opportunities.json
├── triggers/
│   ├── skill-name/
│   │   ├── trigger_eval.json
│   │   └── results.json
│   └── ...
└── quality/
    ├── skill-name/
    │   ├── eval-0/{with_skill,without_skill}/
    │   ├── eval-1/{with_skill,without_skill}/
    │   └── benchmark.json
    └── ...
```

## Integration with Other Skills

- **evaluate-skills**: If evaluate-skills was run recently (check conversation for its output), use its project analysis to generate more relevant test queries
- **skill-creator**: Hand off to skill-creator for fixing broken skills or creating new ones to fill gaps
- When recommending skill removal, always ask the user first — never delete skills automatically
