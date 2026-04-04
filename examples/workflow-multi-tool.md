# Multi-Agent Workflow: New Feature — Tailored for Gemini CLI, Claude Code, and GitHub Copilot

> Ship a well-researched, designed, and implemented product feature using 5 agents — with exact activation syntax for each supported tool.

## The Scenario

Your team needs to add a **user notification preferences** feature to an existing web app: users can choose which email and push notifications they receive, with granular controls per category. The feature needs product validation, UX design, a backend API, frontend implementation, and a production readiness check.

## Agent Team

| Agent | Role in this workflow |
|-------|---------------------|
| Product Manager | Validate the feature scope and define acceptance criteria |
| UX Researcher | Map user expectations and identify design patterns |
| Backend Architect | Design the API and database schema |
| Frontend Developer | Build the React UI |
| Reality Checker | Gate production readiness before shipping |

---

## Tool Setup

Before running this workflow, install the agents for your tool of choice.

### Claude Code

```bash
cp -r agency-agents/product ~/.claude/agents/
cp -r agency-agents/design ~/.claude/agents/
cp -r agency-agents/engineering ~/.claude/agents/
cp -r agency-agents/specialized ~/.claude/agents/
```

Or install all agents at once:

```bash
./scripts/install.sh --tool claude-code
```

### GitHub Copilot

```bash
./scripts/install.sh --tool copilot
```

### Gemini CLI

```bash
./scripts/convert.sh --tool gemini-cli
./scripts/install.sh --tool gemini-cli
```

---

## The Workflow

### Phase 1: Validate the Feature

**Step 1 — Define scope and acceptance criteria**

<details>
<summary><strong>Claude Code</strong></summary>

```
Activate Product Manager.

Feature: User notification preferences for [Your App Name].

Users should be able to:
- Toggle email notifications on/off per category (marketing, transactional, security)
- Toggle push notifications on/off per category
- See a summary of their current preferences
- Save changes without a page reload

Constraints:
- Must not break existing notification sending logic
- Preferences must be respected within 5 minutes of saving
- Mobile and desktop parity required

Deliver:
1. Feature brief with user value statement
2. Acceptance criteria (testable, specific)
3. Out-of-scope list
4. 3 biggest risks to flag for engineering
```

</details>

<details>
<summary><strong>GitHub Copilot</strong></summary>

```
Use the Product Manager agent.

Feature: User notification preferences for [Your App Name].

Users should be able to:
- Toggle email notifications on/off per category (marketing, transactional, security)
- Toggle push notifications on/off per category
- See a summary of their current preferences
- Save changes without a page reload

Constraints:
- Must not break existing notification sending logic
- Preferences must be respected within 5 minutes of saving
- Mobile and desktop parity required

Deliver:
1. Feature brief with user value statement
2. Acceptance criteria (testable, specific)
3. Out-of-scope list
4. 3 biggest risks to flag for engineering
```

</details>

<details>
<summary><strong>Gemini CLI</strong></summary>

```
Use the product-manager skill.

Feature: User notification preferences for [Your App Name].

Users should be able to:
- Toggle email notifications on/off per category (marketing, transactional, security)
- Toggle push notifications on/off per category
- See a summary of their current preferences
- Save changes without a page reload

Constraints:
- Must not break existing notification sending logic
- Preferences must be respected within 5 minutes of saving
- Mobile and desktop parity required

Deliver:
1. Feature brief with user value statement
2. Acceptance criteria (testable, specific)
3. Out-of-scope list
4. 3 biggest risks to flag for engineering
```

</details>

---

### Phase 2: Research + Design (run in parallel)

**Step 2a — UX Researcher: map expectations and patterns**

<details>
<summary><strong>Claude Code</strong></summary>

```
Activate UX Researcher.

I'm designing a notification preferences page for a B2B web app.
Target users: knowledge workers, 25-45, primarily desktop with occasional mobile.

Research task:
1. What mental model do users have for notification preferences?
2. What are the 3 strongest patterns from products like Slack, Linear, and GitHub?
3. What are the top 2 failure modes (where users get confused or abandon)?
4. Recommend a preference hierarchy: global toggle → category → channel, or another structure?

Output a 1-page UX brief with your recommendation and reasoning.
```

</details>

<details>
<summary><strong>GitHub Copilot</strong></summary>

```
Use the UX Researcher agent.

I'm designing a notification preferences page for a B2B web app.
Target users: knowledge workers, 25-45, primarily desktop with occasional mobile.

Research task:
1. What mental model do users have for notification preferences?
2. What are the 3 strongest patterns from products like Slack, Linear, and GitHub?
3. What are the top 2 failure modes (where users get confused or abandon)?
4. Recommend a preference hierarchy: global toggle → category → channel, or another structure?

Output a 1-page UX brief with your recommendation and reasoning.
```

</details>

<details>
<summary><strong>Gemini CLI</strong></summary>

```
Use the ux-researcher skill.

I'm designing a notification preferences page for a B2B web app.
Target users: knowledge workers, 25-45, primarily desktop with occasional mobile.

Research task:
1. What mental model do users have for notification preferences?
2. What are the 3 strongest patterns from products like Slack, Linear, and GitHub?
3. What are the top 2 failure modes (where users get confused or abandon)?
4. Recommend a preference hierarchy: global toggle → category → channel, or another structure?

Output a 1-page UX brief with your recommendation and reasoning.
```

</details>

---

**Step 2b — Backend Architect: design the API (run in parallel with Step 2a)**

<details>
<summary><strong>Claude Code</strong></summary>

```
Activate Backend Architect.

Feature: User notification preferences.

Here's the feature brief and acceptance criteria: [paste Product Manager output]

Current stack: Node.js, PostgreSQL, REST API, Redis for caching.
Existing notifications table has: id, user_id, type, channel, sent_at.

Design:
1. Database schema changes (new tables or columns, with migration strategy)
2. REST API endpoints (method, path, request body, response shape, auth requirement)
3. Caching strategy for preference lookups (latency target: <10ms per lookup)
4. How to propagate preference changes to the existing notification sender within 5 minutes

Deliver as a technical spec with SQL and pseudocode examples.
```

</details>

<details>
<summary><strong>GitHub Copilot</strong></summary>

```
Use the Backend Architect agent.

Feature: User notification preferences.

Here's the feature brief and acceptance criteria: [paste Product Manager output]

Current stack: Node.js, PostgreSQL, REST API, Redis for caching.
Existing notifications table has: id, user_id, type, channel, sent_at.

Design:
1. Database schema changes (new tables or columns, with migration strategy)
2. REST API endpoints (method, path, request body, response shape, auth requirement)
3. Caching strategy for preference lookups (latency target: <10ms per lookup)
4. How to propagate preference changes to the existing notification sender within 5 minutes

Deliver as a technical spec with SQL and pseudocode examples.
```

</details>

<details>
<summary><strong>Gemini CLI</strong></summary>

```
Use the backend-architect skill.

Feature: User notification preferences.

Here's the feature brief and acceptance criteria: [paste Product Manager output]

Current stack: Node.js, PostgreSQL, REST API, Redis for caching.
Existing notifications table has: id, user_id, type, channel, sent_at.

Design:
1. Database schema changes (new tables or columns, with migration strategy)
2. REST API endpoints (method, path, request body, response shape, auth requirement)
3. Caching strategy for preference lookups (latency target: <10ms per lookup)
4. How to propagate preference changes to the existing notification sender within 5 minutes

Deliver as a technical spec with SQL and pseudocode examples.
```

</details>

---

### Phase 3: Build the UI

**Step 3 — Frontend Developer: build the preferences page**

<details>
<summary><strong>Claude Code</strong></summary>

```
Activate Frontend Developer.

Build a notification preferences page for a React + TypeScript app.

UX brief: [paste UX Researcher output]
API spec: [paste Backend Architect output]

Requirements:
- Stack: React, TypeScript, Tailwind CSS
- Optimistic UI: toggle flips immediately, rolls back on API error
- Accessible: keyboard navigable, ARIA labels on all toggles
- Loading and error states for each save operation
- Debounce saves: batch rapid changes into a single API call after 500ms idle

Components needed:
1. NotificationPreferencesPage — top-level page with section headers
2. PreferenceCategory — collapsible category with channel toggles
3. PreferenceToggle — single toggle with label, description, and loading state
4. SaveStatusIndicator — subtle "Saved" / "Saving..." / "Error" badge

Deliver working component code. Include a mock API hook for local testing.
```

</details>

<details>
<summary><strong>GitHub Copilot</strong></summary>

```
Use the Frontend Developer agent.

Build a notification preferences page for a React + TypeScript app.

UX brief: [paste UX Researcher output]
API spec: [paste Backend Architect output]

Requirements:
- Stack: React, TypeScript, Tailwind CSS
- Optimistic UI: toggle flips immediately, rolls back on API error
- Accessible: keyboard navigable, ARIA labels on all toggles
- Loading and error states for each save operation
- Debounce saves: batch rapid changes into a single API call after 500ms idle

Components needed:
1. NotificationPreferencesPage — top-level page with section headers
2. PreferenceCategory — collapsible category with channel toggles
3. PreferenceToggle — single toggle with label, description, and loading state
4. SaveStatusIndicator — subtle "Saved" / "Saving..." / "Error" badge

Deliver working component code. Include a mock API hook for local testing.
```

</details>

<details>
<summary><strong>Gemini CLI</strong></summary>

```
Use the frontend-developer skill.

Build a notification preferences page for a React + TypeScript app.

UX brief: [paste UX Researcher output]
API spec: [paste Backend Architect output]

Requirements:
- Stack: React, TypeScript, Tailwind CSS
- Optimistic UI: toggle flips immediately, rolls back on API error
- Accessible: keyboard navigable, ARIA labels on all toggles
- Loading and error states for each save operation
- Debounce saves: batch rapid changes into a single API call after 500ms idle

Components needed:
1. NotificationPreferencesPage — top-level page with section headers
2. PreferenceCategory — collapsible category with channel toggles
3. PreferenceToggle — single toggle with label, description, and loading state
4. SaveStatusIndicator — subtle "Saved" / "Saving..." / "Error" badge

Deliver working component code. Include a mock API hook for local testing.
```

</details>

---

### Phase 4: Gate Before Shipping

**Step 4 — Reality Checker: production readiness review**

<details>
<summary><strong>Claude Code</strong></summary>

```
Activate Reality Checker.

We're about to ship the notification preferences feature. Run a production readiness check.

Feature brief + acceptance criteria: [paste Product Manager output]
Backend spec: [paste Backend Architect output]
Frontend components: [paste Frontend Developer output]

Check:
1. Does the implementation meet every acceptance criterion? Flag any gaps.
2. Are there security concerns? (auth on all endpoints, preference isolation between users)
3. Are error states handled in both the API and UI?
4. Is there a rollback plan if the migration breaks the existing notifications flow?
5. What's the minimum smoke test to run before flipping the feature flag?

Give a GO / NO-GO decision. If NO-GO, list exactly what must be fixed first.
```

</details>

<details>
<summary><strong>GitHub Copilot</strong></summary>

```
Use the Reality Checker agent.

We're about to ship the notification preferences feature. Run a production readiness check.

Feature brief + acceptance criteria: [paste Product Manager output]
Backend spec: [paste Backend Architect output]
Frontend components: [paste Frontend Developer output]

Check:
1. Does the implementation meet every acceptance criterion? Flag any gaps.
2. Are there security concerns? (auth on all endpoints, preference isolation between users)
3. Are error states handled in both the API and UI?
4. Is there a rollback plan if the migration breaks the existing notifications flow?
5. What's the minimum smoke test to run before flipping the feature flag?

Give a GO / NO-GO decision. If NO-GO, list exactly what must be fixed first.
```

</details>

<details>
<summary><strong>Gemini CLI</strong></summary>

```
Use the reality-checker skill.

We're about to ship the notification preferences feature. Run a production readiness check.

Feature brief + acceptance criteria: [paste Product Manager output]
Backend spec: [paste Backend Architect output]
Frontend components: [paste Frontend Developer output]

Check:
1. Does the implementation meet every acceptance criterion? Flag any gaps.
2. Are there security concerns? (auth on all endpoints, preference isolation between users)
3. Are error states handled in both the API and UI?
4. Is there a rollback plan if the migration breaks the existing notifications flow?
5. What's the minimum smoke test to run before flipping the feature flag?

Give a GO / NO-GO decision. If NO-GO, list exactly what must be fixed first.
```

</details>

---

## Workflow Timeline

| Phase | Step | Agent | Tool notes |
|-------|------|-------|------------|
| 1 | Scope & acceptance criteria | Product Manager | All tools: same prompt, different activation syntax |
| 2a | UX research brief | UX Researcher | Runs in parallel with Step 2b |
| 2b | API + schema design | Backend Architect | Runs in parallel with Step 2a |
| 3 | React UI implementation | Frontend Developer | Needs both 2a and 2b outputs before starting |
| 4 | Production readiness gate | Reality Checker | Needs all previous outputs |

---

## Activation Syntax Reference

| Tool | Syntax | Example |
|------|--------|---------|
| **Claude Code** | `Activate [Agent Name].` | `Activate Product Manager.` |
| **GitHub Copilot** | `Use the [Agent Name] agent.` | `Use the Backend Architect agent.` |
| **Gemini CLI** | `Use the [skill-slug] skill.` | `Use the frontend-developer skill.` |

> **Gemini CLI skill slugs** are lowercase kebab-case versions of the agent name. "Frontend Developer" → `frontend-developer`, "UX Researcher" → `ux-researcher`, "Reality Checker" → `reality-checker`, "Backend Architect" → `backend-architect`, "Product Manager" → `product-manager`.

---

## Key Patterns

1. **Parallel phases reduce wall-clock time**: UX research and API design are independent — start both at the same time, merge their outputs at the build step.
2. **Context passing is explicit**: Always paste the full output of the previous agent into the next prompt. Agents don't share memory between sessions.
3. **Reality Checker is the quality gate**: Don't skip it. It catches gaps between the spec and the implementation before they reach production.
4. **Activation syntax is the only tool-specific difference**: The prompts themselves are identical across Claude Code, GitHub Copilot, and Gemini CLI. Only the first line changes.

## Tips

- If the Reality Checker returns NO-GO, take its specific feedback back to the responsible agent (Backend Architect or Frontend Developer) and ask for a fix. Then re-run the Reality Checker.
- Gemini CLI requires running `./scripts/convert.sh --tool gemini-cli` first to generate the SKILL.md files. Claude Code and GitHub Copilot use the `.md` files directly.
- For long-running features that span multiple sessions, see [workflow-with-memory.md](workflow-with-memory.md) for how to add persistent memory so agents can recall prior context without copy-paste.
