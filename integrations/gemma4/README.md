# Gemma4 Local Integration

Converts all Agency agents into Gemma4-compatible skill files for local use.
Each agent becomes a `SKILL.md` file installed to `~/.gemma/skills/`.

## Install

```bash
# Generate the Gemma4 skill files first
./scripts/convert.sh --tool gemma4

# Then install the skills
./scripts/install.sh --tool gemma4
```

This copies files from `integrations/gemma4/skills/` to `~/.gemma/skills/`.

## Activate a Skill

Reference an agent by its slug name when prompting Gemma4:

```
Use the frontend-developer skill to help me build this UI.
```

## Skill Structure

```
~/.gemma/skills/
  frontend-developer/SKILL.md
  backend-architect/SKILL.md
  reality-checker/SKILL.md
  ...
```

## File Format

Each skill is a `SKILL.md` file with minimal YAML frontmatter:

```yaml
---
name: frontend-developer
description: Expert frontend developer specializing in...
---
```

## Regenerate

After modifying source agents, regenerate the skill files:

```bash
./scripts/convert.sh --tool gemma4
```
