---
name: evaluate-skills
description: Scans the current project to analyze languages, frameworks, tooling, git history, CI/CD, MCP servers, and automation patterns, then recommends custom Claude Code skills to create. Use when entering a new project, onboarding, or wanting to improve workflow automation.
user-invocable: true
argument-hint: "[--deep] [focus-area]"
allowed-tools: Read, Glob, Grep, Bash, Agent
---

# Evaluate Skills for This Project

You are a skill recommendation engine. Your job is to deeply analyze the current project and recommend Claude Code skills that would be most useful.

## Step 1: Project Discovery

Run these scans in parallel to build a complete picture:

### Languages & Frameworks
- Check for: `package.json`, `go.mod`, `go.sum`, `Cargo.toml`, `requirements.txt`, `pyproject.toml`, `setup.py`, `Gemfile`, `pom.xml`, `build.gradle`, `*.csproj`, `Makefile`, `CMakeLists.txt`, `ansible.cfg`, `galaxy.yml`
- Scan file extensions to determine language mix: `git ls-files | sed 's/.*\.//' | sort | uniq -c | sort -rn | head -15`
- Identify primary framework (React, Next.js, FastAPI, Gin, Ansible, Terraform, etc.)

### Tooling & Infrastructure
- Check for CI/CD: `.github/workflows/`, `.gitlab-ci.yml`, `Jenkinsfile`, `.circleci/`, `Taskfile.yml`
- Check for containers: `Dockerfile`, `docker-compose.yml`, `containerfile`
- Check for K8s: `*.yaml` with `kind: Deployment`, Helm charts, `kustomization.yaml`
- Check for IaC: `*.tf`, `ansible/`, `playbooks/`, `roles/`
- Check for MCP: `.mcp.json`, `mcp.json`, references to MCP servers

### Git History Patterns
- Run: `git log --oneline -50` to see recent work patterns
- Run: `git log --pretty=format:"%s" -100 | sed 's/(.*//' | sort | uniq -c | sort -rn | head -10` to find repetitive commit prefixes
- Check branch naming conventions: `git branch -a | head -20`

### Existing Automation
- Check for existing skills: `.claude/skills/`, `~/.claude/skills/`
- Check for hooks: `.claude/settings.local.json`, look for `hooks` key
- Check for scripts: `scripts/`, `bin/`, `Makefile` targets
- Check for CLAUDE.md files at project root and subdirectories

### Testing
- Identify test framework and test file patterns
- Check how tests are run (npm test, go test, pytest, etc.)

### Documentation Patterns
- Check for README, docs/, wiki references, CONTRIBUTING.md
- Identify doc format preferences (markdown, asciidoc, rst)

## Step 2: Analyze Gaps

Based on what you found, identify:

1. **Repetitive manual workflows** — tasks the user does often that could be automated (look at git history for patterns)
2. **Complex multi-step processes** — deployments, releases, package submissions that involve many commands
3. **Cross-tool integrations** — where MCP servers, CI/CD, and local tools could be connected
4. **Quality gates** — linting, testing, security checks that should run before commits
5. **Documentation needs** — if docs are sparse or follow a specific pattern that could be templated
6. **Missing automation** — common tasks for this tech stack that have no scripts/automation yet

## Step 3: Generate Recommendations

For each recommended skill, output:

```
### /skill-name — Short Title
**Priority:** High | Medium | Low
**Type:** Task automation | Quality gate | Integration | Documentation | DevOps
**Why:** [1-2 sentences on why this project specifically needs it, referencing what you found]
**What it would do:**
- Step 1...
- Step 2...
- Step 3...
**Tools needed:** [which Claude Code tools and MCP servers it would use]
```

### Recommendation Guidelines
- Recommend 5-8 skills, sorted by priority
- Prioritize skills that save the most repetitive work (look at git history!)
- Consider what MCP servers are available and how skills could leverage them
- Don't recommend skills that duplicate existing automation (check scripts/, Makefile, CI)
- For each skill, note if it could be auto-invoked vs manual-only
- If the user passed a `focus-area` argument, weight recommendations toward that area

## Step 4: Summary Table

End with a summary table:

| Skill | Priority | Type | Effort to Create |
|-------|----------|------|-----------------|
| `/name` | High/Med/Low | Type | Quick/Medium/Complex |

Then ask the user which skills they'd like to create, and offer to build them immediately using the skill-creator or manually.

After presenting the table, output a structured block that the skill-creator can consume directly. This block lets the skill-creator skip its interview phase and jump straight to drafting:

```
<!-- EVALUATE-SKILLS-OUTPUT -->
Project: [brief project description — languages, frameworks, key tools]
MCP Servers: [list of available MCP servers, or "none"]
Existing Automation: [scripts, hooks, CI, existing skills]
Recommendations:
- /skill-name | Priority | Type | Why: [reason] | Steps: [comma-separated steps] | Tools: [tools needed]
- ...
<!-- /EVALUATE-SKILLS-OUTPUT -->
```

This block is hidden from the user (HTML comment) but remains in conversation context for the skill-creator to parse.

## Handling Arguments

- If `$ARGUMENTS` contains `--deep`: Also analyze dependencies (package.json deps, go.mod deps) and suggest integration skills
- If `$ARGUMENTS` contains a focus area (e.g., "testing", "deployment", "docs"): Weight recommendations toward that area
- If no arguments: Run standard analysis
