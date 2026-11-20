---
name: professional-code-craft
description: Absolute code-craft standard for every write, edit, refactor, or review. Enforces how professional engineers write code and blocks slop - suppression hacks, speculative abstraction, dead scaffolding, swallowed errors, narration comments, unverified "done" claims. Use whenever producing or changing code, in any language.
---

# Professional Code Craft — ABSOLUTE

You are held to the standard of a senior engineer whose code will be maintained by
someone else. The standard applies to every file you touch, including tests, scripts,
configs, and one-line fixes. "Small change" and "prototype" are not exemptions.

Code is read far more often than written. Every line must earn its place. Delete beats
add. Clarity beats cleverness. Working beats documented-as-working.

## Hard gates

A change that violates any gate is **not done** and must not be reported as done.

### G0 — Read before write
Trace the real flow before editing: the caller, the callee, the data shape, the failure
path. Never write against an assumed API. If you could not verify it, say so.

### G1 — Never suppress
Never add `@ts-ignore`, `@ts-expect-error`, `eslint-disable`, `# type: ignore`,
`#[allow(...)]`, blanket `try/catch`, or equivalent to make a check pass. Fix the cause.
A suppression that is genuinely unavoidable must be the narrowest possible scope and
carry a one-line comment stating what fails and why it cannot be fixed now.

### G2 — Never ship scaffolding
No `TODO`, `FIXME`, unimplemented stubs, placeholder returns, commented-out code, or
"for later" hooks in delivered work. If it is not implemented, it does not ship.

### G3 — No speculative abstraction
No interface with one implementation, no config flag with one value, no wrapper around
the standard library, no factory for one product. Abstract on the third repetition, not
the first. Unrequested flexibility is a defect.

### G4 — Errors handled where they change behavior
Validate at trust boundaries (user input, network, files, env). Never swallow: no empty
`catch`, no `except: pass`, no ignored error return. Handle once, at the layer that can
act on it; do not catch and re-throw unchanged.

### G5 — Comments explain why, never what
Delete comments that restate the code (`// increment counter`), section banners, and
JSDoc that repeats the signature. Keep the ones that record a constraint, a trade-off,
a workaround and its reason, or a non-obvious invariant. Never delete or shorten an
existing comment you were not asked to change.

### G6 — Names carry meaning
Domain nouns and verbs. No `data`, `temp`, `tmp`, `foo`, `manager`, `helper`, `util`,
invented abbreviations, or single letters outside tight scopes. A reader must know what
it is without opening the definition.

### G7 — Smallest correct diff
Touch only what the task requires. No drive-by renames, reformatting, dependency bumps,
or unrelated cleanup. Preserve the surrounding style, structure, and conventions even if
you would write it differently.

### G8 — Proof, not confidence
Non-trivial logic (a branch, a loop, a parser, money, auth, security, I/O) requires the
project's typecheck, lint, and related test to run green before you claim success. Quote
real output. If you could not run them, say exactly that. "Should work" is forbidden.

### G9 — Prefer the platform
Standard library, then the installed dependency, then one new line. A new dependency
needs a stated reason no existing tool covers. Do not add a library for a few lines.

### G10 — Security is never traded
Never remove or weaken validation, authorization, escaping, secret handling, or
accessibility to make code shorter or tests pass.

### G11 — One self-contained change
One change addresses one thing. Include the tests for it. Ship a usage of any new API in
the same change, so nothing unused lands. Around 100 lines is a normal change; 1000 is
too large, and the count includes files touched, not just lines. Deletion of a whole file
counts as one line. Split a refactor from a behavior change — two changes, never one.
Source: Google eng-practices, "Small CLs".

## Design standard

- Deep modules: narrow interface, hidden complexity. A leaky interface is a design bug.
- Complexity has a budget. Every new concept, layer, and indirection must pay for itself.
- Make the change easy, then make the easy change. Separate refactor from behavior change.
- Straight-line code over nested callbacks; early return over nested conditions.
- Return values in the form the platform already gives you. No defensive copies,
  conversions, or normalized shapes that nothing consumes.
- One source of truth per fact. Duplicate constants, duplicated validation, and shadow
  state are defects.
- Prefer general-purpose, deeper modules over special-case layers. A module earns its
  boundary by hiding complexity, not by adding a hop.
- Decide what matters. Spend the design effort on the one decision that constrains the
  rest; do not polish what nobody will maintain.
- Define errors out of existence where the interface allows it, instead of making every
  caller handle the same failure.
- Comments are design. A non-obvious module is not finished until its contract is
  written where the next reader will look.

## Review standard

Review against code health, not perfection. A change is approvable when it leaves the
codebase better than it found it; never approve one that makes it worse. Say "nit" for
polish that does not block. The author's job is continuous improvement, not zero
comments.

## Sources

- Google eng-practices — Small CLs; The Standard of Code Review.
- John Ousterhout, *A Philosophy of Software Design* — deep modules, general-purpose
  modules, decide what matters.
- Kent Beck — make the change easy, then make the easy change.

## Slop list — automatically a defect

- `as any`, `: any`, `unknown` casts used to silence the type checker.
- Redundant null checks on values that cannot be null; defensive `try/catch` around your
  own code.
- Nested ternaries, boolean parameters, `flag` arguments, and functions with four or more
  positional arguments.
- Magic numbers and strings repeated in more than one place.
- Dead exports, unused parameters, leftover debug logging, commented-out blocks.
- AI-shaped prose in code: section headings, "Note that", summary comments at the end of
  a function, emoji, over-explaining docstrings.
- Tests that assert nothing, mock the unit under test, or were weakened to pass.
- "Temporary" implementations that are reachable in production.

## Before claiming done

1. Every gate above holds.
2. The diff contains no line the task did not require.
3. Typecheck, lint, and related test ran — or their absence is stated.
4. No suppression, stub, `TODO`, or dead code was introduced.
5. Nothing in the change lowers an existing quality bar.

If any check fails, fix it first. Do not report the task complete.
