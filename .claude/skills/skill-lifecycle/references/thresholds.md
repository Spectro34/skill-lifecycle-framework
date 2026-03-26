# Skill Lifecycle Thresholds

All tunable numbers used by the orchestrator and its scripts. Change these to adjust sensitivity.

## Testing Phase (Pass/Fail Criteria)

| Metric | PASS | MARGINAL | FAIL |
|--------|------|----------|------|
| Trigger F1 | >= 0.80 | 0.50 - 0.80 | < 0.50 |
| Quality Delta | >= +15% | +5% to +15% | < +5% |
| Token Overhead | < 2x baseline | 2x - 3x | > 3x |

A skill must meet BOTH trigger F1 AND quality delta thresholds to auto-pass.
Marginal on either metric → user decides. Fail on either → iterate or discard.

## Churn Decision Thresholds

| Condition | Threshold | Action |
|-----------|-----------|--------|
| Broken triggering | F1 < 0.50 | FIX_DESCRIPTION |
| No quality improvement | delta < 5% | REWRITE_OR_REMOVE |
| Dormant | No usage in 30 days | REVIEW_FOR_REMOVAL |
| Declining trend | F1 dropping across 3+ audits | INVESTIGATE |

## Usage Classification

| Status | Definition |
|--------|-----------|
| Active | Used within the last 30 days |
| Dormant | Previously used, but not in the last 30 days |
| Never Used | No evidence of invocation or relevant sessions ever |

## Description Optimization

| Parameter | Value | Notes |
|-----------|-------|-------|
| Max iterations | 5 | For run_loop.py |
| Train/test split | 60/40 | Stratified by should_trigger |
| Runs per query | 2-3 | Higher = more reliable, slower |
| Trigger threshold | 0.50 | Rate at which we count a trigger |

## Sandbox Testing

| Parameter | Value | Notes |
|-----------|-------|-------|
| Runs per query (trigger) | 2 | Minimum for reliable signal |
| Test prompts (quality) | 2-3 | Per skill |
| Timeout per query | 30s | For run_eval.py |
| Max parallel workers | 10 | For ProcessPoolExecutor |
