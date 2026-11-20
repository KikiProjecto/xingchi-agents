---
name: master-prompt
description: Write a complete implementation spec before multi-file or ambiguous work. Use when a task touches several files, the request is vague, or a session risks clarification loops. Produces a five-part master prompt (role, do-not-touch, discovery, numbered issues, acceptance criteria), then executes it in one pass.
---

# Master Prompt

Conversational implementation burns tokens three ways: the agent guesses intent, crawls the codebase, and guesses constraints. Do that thinking once, up front, then execute against it.

## When
Any task larger than a two-file fix, or any request that leaves scope or "done" ambiguous.

## The five parts
1. **Role / context** — the engineer you are acting as, the stack, the constraints. Two to four lines. Include a condensed project brief (10 lines max), not raw docs.
2. **Do-not-touch** — files, areas, patterns that are off limits. If none, say "nothing else".
3. **Phase 0 discovery** — exact `rg`/`git`/read commands aimed at the files that matter. Run those; do not crawl.
4. **Numbered issues** — each with current state, required end state, and files it touches.
5. **Acceptance criteria** — observable checks: browser, endpoint, CLI, or test output. Not "it compiles".

Template: `assets/master-prompt.md`.

## Rules
- Keep the spec in the conversation, not in a file the agent must re-open.
- Discovery before code. One commit per concern.
- Verification must be real; assumed success is a defect (professional-code-craft G8).
- If a fact is only the user's to give (target file, non-goal), ask once, then write the spec.

## Output
Write the filled spec, then execute it in the same turn unless the user asked for the spec alone.
