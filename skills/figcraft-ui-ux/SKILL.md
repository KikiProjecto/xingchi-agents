---
name: figcraft-ui-ux
description: Professional UI/UX execution system for FigCraft MCP. Use this skill whenever the user mentions FigCraft, FigCraft MCP, .figcraft, designing or editing screens, frames, layouts, spacing, auto layout, components, variants, design systems, tokens, or prototypes; whenever a FigCraft document needs to be created, cleaned up, or made to look professional; and whenever the user asks for faster FigCraft work or higher design quality, even if they do not say "UI/UX." It enforces real frames, auto layout, a 4/8pt spacing system, tokenized styles, component reuse, accessibility, and batch-first execution.
---

# FigCraft UI/UX Professional Execution

Goal: every FigCraft document is structurally clean, visually professional, and built in as few MCP round trips as possible.

## Non-negotiables

1. **Frames, not floating layers.** Every screen is a top-level frame. Every section, card, and modal is a frame. Groups are only for non-layout bundles such as icons and masks.
2. **Auto layout for every stack and row.** No manual `x`/`y` for children of an auto-layout frame, except intentional `absolute: true` overlays.
3. **Spacing only from the scale:** 4, 8, 12, 16, 24, 32, 48, 64, 96. Never 5, 10, 15, 18, 20, 25, 30.
4. **Type only from the ramp.** Body 16/24, secondary 14/20, caption 12/16, headings 20/28, 24/32, 32/40. Styles Regular, Medium, SemiBold, Bold.
5. **Color roles, not random hex.** One accent. Neutral background, surface, text, and border tokens. Contrast at least 4.5:1 for body text and 3:1 for large text and UI boundaries.
6. **Touch targets at least 44×44.** Interactive controls need hover, pressed, and disabled states.
7. **Reuse before drawing.** Inspect existing components, variants, and styles first. A repeated element becomes a component.
8. **Verify with numbers and pixels.** `inspect_document` for structure, `screenshot` for appearance. Never claim "done" without both.

## Session workflow

### 0. Inspect once, not repeatedly

```
inspect_document {depth: 2, outline: true}
```

Use the result to find existing pages, frames, components, and styles. Only call `list_commands {filter: "..."}` when you are genuinely unsure a command exists. Never re-inspect after every edit.

### 1. Establish tokens before drawing

Create variables and styles only when the document does not already have them. Check with `run_command {command: "variable.list"}`; the collection must exist before its first variable.

```
run_command {command: "variable.createCollection", params: {name: "Color"}}
run_command {command: "variable.create", params: {
  collection: "Color", name: "surface/canvas", type: "color", value: "#F7F8FA"
}}
run_command {command: "variable.create", params: {
  collection: "Space", name: "space/16", type: "number", value: 16
}}
run_command {command: "style.create", params: {
  type: "text", name: "Body/Regular",
  value: {fontFamily: "Inter", fontStyle: "Regular", fontSize: 16, lineHeight: 24}
}}
```

Use variable references (`{$var: "surface/canvas"}`) in fills and strokes. Use `textStyle` or `style.apply` for typography. If the file already has tokens, bind to them instead of creating near-duplicates.

### 2. Build the frame skeleton first

Create each screen as a frame with a fixed device size, then add regions as auto-layout frames:

- Mobile: 393×852, 20 or 24 side padding, safe top 59, safe bottom 34.
- Tablet: 834×1194, 32 side padding.
- Desktop: 1440×1024, content max width 1200, 12-column grid, 24 gutter.

Top-level structure for a typical screen:

```
Screen (vertical, sizingV: fixed, width 393)
├── Status bar / safe area (absolute or fixed 59)
├── Header (horizontal, padding 20/16, gap 12, crossAlign center)
├── Scroll content (vertical, fill height, padding 20, gap 24)
│   ├── Section (vertical, gap 12)
│   └── Section (vertical, gap 16)
└── Tab bar / bottom action (horizontal, fixed 72 + safe bottom)
```

Set `layout`, `gap`, `padding`, `mainAlign`, `crossAlign`, `sizingH`, and `sizingV` in the same `create_node` or `set_properties` call that creates the frame. Do not create a frame, then set layout in a second call.

### 3. Fill content in dependency order

Create parents before children. Inside a `batch`, reference earlier results:

```json
{"command": "create_node", "params": {"type": "frame", "name": "Screen", "width": 393, "height": 852,
  "props": {"layout": "vertical", "sizingH": "fixed", "sizingV": "fixed"}}, "as": "screen"}
{"command": "create_node", "params": {"type": "frame", "name": "Header", "parent": {"$ref": "screen"},
  "props": {"layout": "horizontal", "padding": [0, 20, 0, 20], "gap": 12, "crossAlign": "center",
  "sizingH": "fill", "sizingV": "hug"}}}
```

For text, set `width`/`height` only when fixed is intentional. Otherwise let the frame hug and use `maxWidth` to control wrapping.

### 4. Verify in two passes

```
inspect_document {depth: 3, outline: true}
screenshot {ids: [screenId], scale: 1}
```

First pass checks structure and geometry. Second pass checks the rendered pixels. Fix, then re-screenshot only the changed screen.

### 5. Save safely

Always save to `~/Prototypes/<name>.figcraft`:

```
save_file {path: "<HOME>/Prototypes/<name>.figcraft"}
```

The Flatpak sandbox only allows writes there. A successful save outside that folder is not durable.

## Fast execution rules

- **One batch per screen.** Group all creates and property updates for a screen into one `batch` call. `batch` is one undo step and one round trip.
- **Use step references.** Name steps with `"as"` and reference them with `{"$ref": "name"}`. This removes the need to inspect IDs between calls.
- **Create with props.** `create_node` accepts `props`, so layout, fill, stroke, radius, and typography can land at creation time.
- **Prefer setting `layout` over invoking `layout.add`.** Use `layout.add` only to convert existing layers. Use `layout.suggest` when converting a manually drawn screen whose grouping you cannot infer.
- **Set sizing deliberately.** `hug` for content-sized frames and text, `fill` for children that should stretch, `fixed` for screens and bars. A child cannot `fill` an axis its parent hugs.
- **Use `distribute` and `align` for one-off cleanup**, not as the primary construction method. Construction should already be correct through auto layout.
- **Cache command knowledge.** Do not call `list_commands` for commands documented here. `run_command` and `batch` reach the same engine as the menus.
- **Check the response of each batch.** If a step fails, fix that step and rerun; do not blindly repeat the whole batch after an attach transport error, because the app may already have applied it.

## Component and variant strategy

Build repeated UI once:

```
component.create {ids: [buttonFrame]}
component.createMultiple {ids: [primaryId, secondaryId]}
component.combineVariants {ids: [primaryId, secondaryId]}
component.addVariant {id: setOrVariantId, property: "State", value: "Pressed"}
instance.create {component: componentId, parent: rowId, x: 0, y: 0}
```

Use `set_properties` on an instance only for content overrides. Structural changes belong in the main component. Place instances with `instance.create` when the parent is auto layout; use `instance.place` only for free page placement.

## Prototype rules

- One primary action per screen. Every interactive layer has a destination or a state change.
- Use `proto.interaction.add {id, dest}` for simple click navigation.
- Use `transition: {type: "smartAnimate"}` only when the same elements exist on both screens. Otherwise use `dissolve` or `moveIn`.
- Duration 200-300ms, easing `easeOut` or `gentle`. Never animate more than one property family at once.
- Overlays for menus and sheets; navigation for screens.

## Quality gates

A screen is not done until all of these are true:

- [ ] Root is a top-level frame at a real device size.
- [ ] Every stack and row uses auto layout; no stray manual positioning.
- [ ] All gaps and padding come from the spacing scale.
- [ ] Type uses the ramp; no one-off font sizes or weights.
- [ ] Colors resolve to variables or styles; no accidental defaults.
- [ ] Contrast: body text 4.5:1, large text and UI boundaries 3:1.
- [ ] Touch targets at least 44×44.
- [ ] Repeated elements are component instances, not copies.
- [ ] Text does not overflow or clip unintentionally at the target width.
- [ ] Screenshot confirms alignment, hierarchy, and spacing.

If a gate fails, fix it before reporting completion.

## Reference files

Read only the file the task needs:

- `references/mcp-fast-path.md` — exact batch recipes, command parameters, and response handling.
- `references/layout-and-spacing.md` — layout patterns, sizing rules, spacing decisions, and common fixes.
- `references/design-quality.md` — type scale, color roles, accessibility, visual QA, and anti-slop rules.

## Design bans

No neon, rainbow or gradient chrome, glassmorphism, glow, emoji-as-UI, or stock blob heroes. Solid colors, a limited palette, typography first, generous whitespace. If the user explicitly asks for a banned style, follow the request but keep hierarchy and contrast intact.
