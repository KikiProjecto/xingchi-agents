# Design Quality

## Color roles

Define roles, not individual colors. A document needs one accent and a neutral ramp.

| Role | Light | Dark |
|---|---|---|
| Canvas | `#F7F8FA` | `#0B0F14` |
| Surface | `#FFFFFF` | `#141A21` |
| Surface muted | `#F1F3F5` | `#1B232C` |
| Border | `#E5E7EB` | `#26303A` |
| Text primary | `#111827` | `#F3F4F6` |
| Text secondary | `#6B7280` | `#9CA3AF` |
| Text disabled | `#9CA3AF` | `#6B7280` |
| Accent | `#4F46E5` | `#818CF8` |
| Accent hover | `#4338CA` | `#A5B4FC` |
| Success | `#15803D` | `#4ADE80` |
| Warning | `#B45309` | `#FBBF24` |
| Danger | `#B91C1C` | `#F87171` |

Rules:

- One accent color per screen. Use it for the primary action, active navigation, and focus.
- Status colors are semantic only. Never use success green as a decorative accent.
- No pure `#000000` text. No `#FFFFFF` text on a light surface.
- Borders are one step darker than the surface they separate. Do not use shadows where a border is enough.
- Tint backgrounds from the accent only at 4-8% opacity for selected states.

Contrast minimums:

- Body text: 4.5:1.
- Large text (24px regular or 18.66px bold and up): 3:1.
- Icons and UI boundaries: 3:1.
- Disabled controls are exempt from contrast but must still read as controls.

Do not encode meaning in color alone. Pair status color with an icon or label.

## Type ramp

| Token | Size / line | Style | Use |
|---|---|---|---|
| Display | 40/48 | Bold | Marketing hero only |
| H1 | 32/40 | Bold | Screen title |
| H2 | 24/32 | SemiBold | Major section |
| H3 | 20/28 | SemiBold | Card title, subsection |
| Body L | 16/24 | Regular | Default body |
| Body | 14/20 | Regular | Dense UI, secondary body |
| Label | 12/16 | SemiBold | Buttons, field labels, tabs |
| Caption | 12/16 | Regular | Helper text, metadata |

Rules:

- Maximum three sizes on one screen, excluding display.
- Body text at 16px minimum on mobile. Never 13px or 11px for primary content.
- Line height 1.4-1.5 for body, 1.15-1.25 for headings.
- Letter spacing: 0 for body, `-0.02em` for large headings, `0.02em` for uppercase labels.
- Use the document's existing font family. For a new document, use Inter or the platform sans that FigCraft has available. Never set a font family that is not installed.
- Sentence case for headings and buttons. Title Case only for proper nouns.
- Maximum line length 60-75 characters. Use `maxWidth: 720` for long-form text.

## Spacing and shape

- Spacing scale: 4, 8, 12, 16, 24, 32, 48, 64, 96.
- Radius scale: 4, 8, 12, 16, 24, full. Pick one radius per component family.
- Buttons: 8 or 12. Cards: 12 or 16. Sheets and modals: 20 or 24. Avatars and pills: full.
- Border width: 1px for separation, 2px for focus rings. Never 3px decorative borders.
- Shadow: at most one soft elevation level. `0 1px 2px rgba(0,0,0,0.06)` for cards, `0 8px 24px rgba(0,0,0,0.12)` for modals. No colored glows.

## Accessibility

- Touch targets at least 44×44, with at least 8px between separate targets.
- Focus state is always visible: 2px accent ring with 2px offset.
- Every icon-only button has a text label in its layer name and, in production, an accessible name.
- Text is never baked into an image when it can be a text layer.
- Form fields have visible labels. Placeholder is not a label.
- Error text sits next to the field and states the fix.
- Motion respects reduced motion. Keep essential transitions under 300ms.
- Reading order follows layer order. Put decorative layers after content in the tree.

## Component states

Every interactive component needs these variants when the product is real:

- Default
- Hover
- Pressed
- Focus
- Disabled
- Loading, for actions that take time
- Error, for inputs

At minimum, design Default, Pressed, and Disabled. A component without states is a drawing, not a component.

## Content quality

- Buttons: verb first, one to three words. "Save changes", not "Submit".
- Empty states: say what is empty, why it matters, and the next action.
- Errors: what happened, what to do. No blame, no error codes alone.
- Labels: sentence case, no trailing colon.
- Numbers: tabular figures for tables and prices.
- Dates: unambiguous. "31 Oct 2026", not "10/31/26".

## Visual QA checklist

Look at the screenshot, not only the JSON.

- [ ] One clear focal point per screen.
- [ ] Left edges align across sections.
- [ ] Gaps are visually equal within a group and larger between groups.
- [ ] Text baselines align in rows.
- [ ] Icons are optically centered, not mathematically off by a pixel.
- [ ] No text touches a frame edge or clips.
- [ ] No element overflows the screen at 393px.
- [ ] Radii are consistent within a component family.
- [ ] Only one accent color is visible.
- [ ] Disabled and secondary elements still read as interactive or inert, correctly.
- [ ] There is enough whitespace for the content to breathe.

## Anti-slop rules

Do not use, unless the user explicitly asks:

- Gradients, neon, glow, or rainbow chrome.
- Glassmorphism, frosted panels, or blur as decoration.
- Emoji as UI icons.
- Decorative blobs, stock hero illustrations, or abstract shapes with no function.
- Giant shadows or floating cards on every surface.
- Every element in a pill or rounded rectangle.
- Six accent colors competing for attention.
- Centered body text in a left-aligned product UI.
- Low-contrast gray text as a style choice.
- Icon soup: more than one icon per action or decorative icons beside every label.

Good design here means solid colors, a small palette, strong type hierarchy, consistent spacing, and obvious affordances.
