---
name: token-audit
description: Measure the static context cost of the Claude setup - skill listing, agents, commands, MCP servers, and CLAUDE.md - without reading files into the conversation. Use when asked about token usage, context budget, setup bloat, or which skills and MCP servers to prune.
---

# Token Audit

Run `scripts/token-audit.sh`. It prints approximate per-component costs (chars/4) and the heaviest entries; only the summary enters the conversation.

## Rules
- Do not read skill bodies to estimate cost. Listing cost is frontmatter name plus description.
- MCP cost is server count plus deferred tool names; schemas load on demand.
- Prune before compressing prose. Dropping one unused MCP server beats rewriting ten skills.
- Report numbers, not adjectives.
