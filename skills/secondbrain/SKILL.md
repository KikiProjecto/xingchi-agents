---
name: secondbrain
description: Second Brain access protocol. Use when the user says "SECONDBRAIN", references the vault (~/SecondBrain), asks about past sessions/decisions/knowledge, or wants to query the brain. Index-first, search-don't-scan, token-lean. Never read more than 1-2 small files to orient.
allowed-tools: [Read, Write, Edit, Bash, Glob, Grep]
---

# secondbrain — token-lean knowledge base

Vault: `~/SecondBrain`. Plain markdown, git-backed. Obsidian = human viewer only; Claude touches filesystem only.

## Read (answer from the brain)
1. Read `00-INDEX.md` FIRST — the only overview file (~150-300 tokens). Orients to active projects.
2. Search, don't scan: `rg "term" ~/SecondBrain -l` → open only the 1-3 matches that matter.
3. Newest session only by default. Older sessions = explicit request, max 2-3 more.
4. Check status via frontmatter: `rg -l "status: blocked"` — never open files just to check state.

## Write
1. New session note (append-only): `projects/<slug>/sessions/<timestamp>.md`
2. New decision → prepend one line to `decisions.md` (newest first, with rationale).
3. Reusable fact → `knowledge/<topic>.md`; reusable code → `snippets/<topic>.md`. Link, don't inline.
4. Refresh index: `_scripts/update_index.sh`.

## Hard token rules
- Never glob or recursive-read the vault. Exact paths only (index or rg hit).
- Note >300 words → split: short pointer in the log, substance in knowledge/snippets, link it.
- No duplicate content. Link existing knowledge, never re-paste "for context".
- Sessions >2 weeks → `_scripts/compact.sh` rolls into `archive/YYYY-MM/<project>-summary.md`.

## Structure
```
00-INDEX.md          ← only full overview, read first
projects/<slug>/     ← _meta.md (status/stack), decisions.md, sessions/, snippets/
knowledge/<topic>.md ← durable facts (atomic, not logs)
daily/               ← optional cross-project rollup
archive/YYYY-MM/     ← compacted old sessions, never read unless asked
```
