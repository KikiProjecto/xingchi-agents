# Layout and Spacing

## The spacing scale

Use only these values: **4, 8, 12, 16, 24, 32, 48, 64, 96**.

| Value | Use |
|---|---|
| 4 | Icon-to-label, badge inset, tight text pair |
| 8 | Inline items, button icon gap, label-to-value |
| 12 | Compact card padding, list row internal gap |
| 16 | Standard card padding, mobile screen gutter, control gap |
| 24 | Section gap, desktop gutter, card grid gap |
| 32 | Major section separation, modal padding |
| 48 | Page-level rhythm, large section separation |
| 64, 96 | Hero or marketing spacing only |

Decision rule: pick the smallest value that keeps related items visibly together and unrelated items clearly apart. When two values both look plausible, use the lower one inside a component and the higher one between components.

## Sizing rules

| Element | Horizontal | Vertical |
|---|---|---|
| Screen frame | fixed | fixed |
| Header | fill | hug |
| Main content region | fill | fill |
| Section frame | fill | hug |
| Text | hug or fill with maxWidth | hug |
| Button | hug, minWidth 44 | fixed 48 (mobile) or 40 (desktop) |
| Icon button | fixed 44 | fixed 44 |
| List row | fill | hug, minHeight 56 |
| Card | fill in grid | hug, or fixed when media has a fixed aspect |
| Divider | fill | fixed 1 |
| Bottom bar | fill | fixed 64 + safe area |

Never let a parent hug an axis while a child fills it. FigCraft resolves this by changing one side; set the parent to `fixed` or the child to `hug` deliberately.

## Screen shells

### Mobile, 393×852

```
Screen (vertical, fixed 393×852, padding 0)
├── Safe area top (fixed 59, optional absolute)
├── Header (horizontal, fill × hug, padding 16/20)
├── Content (vertical, fill × fill, padding 20, gap 24)
└── Bottom bar (horizontal, fill × fixed 64 + safe bottom)
```

Content sections:

```
Section (vertical, fill × hug, gap 12)
├── Section header (horizontal, fill × hug, gap 8, crossAlign center)
├── Section body (vertical, fill × hug, gap 12)
└── Section footer (horizontal, fill × hug, mainAlign spaceBetween)
```

### Desktop, 1440×1024

```
Page (horizontal, fixed 1440×1024)
├── Sidebar (fixed 240 × fill, padding 24, gap 8)
└── Main (vertical, fill × fill, padding 32, gap 32)
    ├── Top bar (horizontal, fill × hug, gap 16, crossAlign center)
    └── Content (grid, fill × fill, gridColumns 12, columnGap 24, rowGap 24)
```

Constrain reading width with `maxWidth: 720` on article text. Do not let paragraphs span a 1440px screen.

## Common patterns

### Header

`layout: horizontal`, `padding: [16, 20, 16, 20]`, `gap: 12`, `crossAlign: center`, `sizingH: fill`, `sizingV: hug`.

- Title: `sizingH: fill`, `maxLines: 1`.
- Actions: fixed 44×44 icon buttons, gap 8.
- Optional bottom divider: separate frame, height 1, fill border color, no padding.

### Vertical list

`layout: vertical`, `gap: 0`, `sizingH: fill`, `sizingV: hug`. Each row:

`layout: horizontal`, `padding: [16, 20, 16, 20]`, `gap: 12`, `crossAlign: center`, `sizingH: fill`, `sizingV: hug`, `minHeight: 56`.

Use `gap: 0` with row padding when rows have dividers. Use `gap: 8` or `12` when rows are separate cards.

### Card grid

`layout: grid`, `gridColumns: 2`, `columnGap: 12`, `rowGap: 12`, `sizingH: fill`, `sizingV: hug`.

Set tracks only when columns differ: `columnTracks: ["1fr", "1fr"]`. Otherwise let `gridColumns` distribute evenly.

Each card: `layout: vertical`, `padding: 16`, `gap: 12`, `sizingH: fill`, `sizingV: hug`.

### Form

```
Form (vertical, fill × hug, gap: 24)
└── Field (vertical, fill × hug, gap: 8)
    ├── Label (hug, 14/20, Medium)
    ├── Input (fill × fixed 48, padding 12/16, radius 12)
    └── Helper or error (hug, 12/16)
```

Group related fields at gap 16; separate field groups at gap 24.

### Bottom action bar

`layout: horizontal`, `padding: [12, 20, 12 + safeBottom, 20]`, `gap: 12`, `crossAlign: center`, `sizingH: fill`, `sizingV: fixed` with height 64 plus the safe inset.

Primary action fills remaining width. Secondary action hugs or is an icon button.

### Modal or sheet

Overlay frame fills the screen, `fill: "#000000"`, `opacity: 0.35`, content aligned center or bottom.

Sheet: `layout: vertical`, `padding: [24, 20, 20, 20]`, `gap: 20`, `sizingH: fill`, `sizingV: hug`, bottom corners radius 24.

Modal: width 343 on mobile or `maxWidth: 480`, `padding: 24`, `gap: 20`, radius 20, `sizingH: fill`, `sizingV: hug`.

## Alignment and rhythm

- Align text to a shared left edge. Never center body text in a left-aligned layout.
- Use `crossAlign: "center"` for icon + label rows. Use `baseline` only for mixed text sizes on one line.
- Use `mainAlign: "spaceBetween"` for header title/action pairs and list row label/trailing value.
- Do not use `spaceAround` or `spaceEvenly` for forms or lists. They create unpredictable gaps.
- Every screen has one dominant element. If everything is bold, nothing is.

## Fixing an existing messy frame

1. Select the frame's children and run `layout.suggest` once. It infers direction from geometry.
2. Set `gap` to the nearest scale value. Do not keep the inferred arbitrary gap.
3. Set `padding` to the scale value nearest the current visual inset.
4. Convert fixed children to `hug` or `fill` based on the sizing table.
5. Delete spacer layers. Auto layout gaps replace them.
6. Re-screenshot. If the result shifts, fix the sizing before adjusting gaps.

For a screen with floating absolute layers, wrap related layers in a frame, run `layout.add`, then set gap and padding. Use `absolute: true` only for overlays, badges, and background decoration.

## Red flags

- A gap or padding value not on the scale.
- A frame with `layout: null` that contains a vertical stack or row.
- Fixed heights on text or content cards.
- A `fill` child inside a `hug` parent on the same axis.
- Spacer frames or invisible rectangles used to create distance.
- More than two levels of nesting for a simple card.
- Content clipped at the frame edge because the root is fixed and children overflow.
