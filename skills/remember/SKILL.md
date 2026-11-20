---
name: remember
description: Save session memory. On "REMEMBER" / "SAVE THIS" / "SUMMARIZE" / "MAKE A SUMMARY", extract 5-10 critical points (decisions, code, paths, configs, next steps) into a copy-paste summary AND persist to the Second Brain vault (~/SecondBrain) as an append-only session note. Use whenever the user wants cross-session continuity or to preserve context.
allowed-tools: [Read, Write, Edit, Bash, Glob, Grep]
---

# remember — persist session to Second Brain

Trigger: "REMEMBER", "SAVE THIS", "SUMMARIZE", "MAKE A SUMMARY", "CREATE A SUMMARY".

## Steps
1. Read `~/SecondBrain/00-INDEX.md` (cheap, ~200 tokens) → find/create project slug. Use user-named project if given.
2. Write NEW append-only file `~/SecondBrain/projects/<slug>/sessions/YYYY-MM-DD-HHmm.md`. Never rewrite old sessions.
3. Genuinely new decision → prepend ONE line to `projects/<slug>/decisions.md` (newest first, include "why").
4. Reusable code block >15 lines → write `projects/<slug>/snippets/<topic>.md`, link from session note, never inline.
5. Run `~/SecondBrain/_scripts/update_index.sh` to refresh 00-INDEX.md.
6. Print 5-10 bullet summary to chat (copy-paste ready).

## Vault rules (full contract in ~/SecondBrain/CLAUDE.md)
- Open files only by exact path from index or `rg` hit. Never glob/scan the vault.
- Read newest session only by default.
- Write short, link long. Note >300 words → split.
- No duplicate content — link existing knowledge, don't re-paste.

## Summary format (output to chat)
```
## CONVERSATION SUMMARY
### Context — what built/solved
### Decisions — with rationale, not just "what"
### Code & Config — exact paths, language-tagged snippets, versions
### Errors fixed — repro + fix
### Next steps — clear + actionable
```
5-10 bullets total. Preserve code blocks, exact paths, non-secret config values.

## Never include
Secrets, API keys, tokens.
