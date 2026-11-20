# FigCraft MCP Fast Path

Exact tool and command usage. Prefer this over experimentation.

## Tool selection

| Need | Tool |
|---|---|
| Create layers | `create_node` |
| Change any property | `set_properties` |
| Run an engine command | `run_command` |
| Several edits, one undo step | `batch` |
| Read structure | `inspect_document`, `get_node` |
| Look at pixels | `screenshot` |
| Save | `save_file` |
| Export | `export` |
| Select layers | `select` |
| Discover commands | `list_commands` |

`run_command` and `batch` reach every menu command. `create_node`, `set_properties`, `inspect_document`, `get_node`, `screenshot`, `select`, `export`, `open_file`, and `save_file` are dedicated tools.

## Batch shape

```json
{
  "label": "Home screen",
  "commands": [
    {"command": "create_node", "params": {"type": "frame", "name": "Screen", "width": 393, "height": 852,
      "props": {"layout": "vertical", "sizingH": "fixed", "sizingV": "fixed", "fill": "#F7F8FA"}}, "as": "screen"},
    {"command": "create_node", "params": {"type": "frame", "name": "Header", "parent": {"$ref": "screen"},
      "props": {"layout": "horizontal", "padding": [16, 20, 16, 20], "gap": 12, "crossAlign": "center",
      "sizingH": "fill", "sizingV": "hug"}}, "as": "header"},
    {"command": "create_node", "params": {"type": "text", "name": "Title", "parent": {"$ref": "header"},
      "text": "Discover", "props": {"fontSize": 28, "fontStyle": "Bold", "lineHeight": 36,
      "fill": "#111827", "sizingH": "fill", "sizingV": "hug", "maxLines": 1}}}
  ]
}
```

- `parent` accepts a layer id or `{"$ref": "stepName"}`.
- Name a step with `"as"`, then use `{"$ref": "name"}` anywhere in a later step's params.
- `{"$step": 0}` references by zero-based position.
- Use `"field": "ids/0"` to take part of a result.
- A failed step is removed from the journal, but earlier steps stay applied. Read the error and fix that step.

## Create-node parameters

```
create_node {
  type: frame|rectangle|ellipse|polygon|star|line|arrow|text|vector|section|component|slice,
  x?, y?, width?, height?, parent?, index?, name?, text?, path?, props?
}
```

`x`/`y` are relative to the parent frame. For auto-layout children, omit them and use `props`.

## Auto layout properties

Set these on a frame through `create_node.props` or `set_properties`:

| Key | Values |
|---|---|
| `layout` | `"horizontal"`, `"vertical"`, `"grid"`, `null` |
| `gap` | number |
| `crossGap` | number; row gap for wrapped horizontal layouts |
| `padding` | number or `[top, right, bottom, left]` |
| `mainAlign` | `min`, `center`, `max`, `spaceBetween`, `spaceAround`, `spaceEvenly` |
| `crossAlign` | `min`, `center`, `max`, `baseline` |
| `sizingH`, `sizingV` | `fixed`, `hug`, `fill` |
| `wrap` | boolean |
| `minWidth`, `maxWidth`, `minHeight`, `maxHeight` | number |
| `absolute` | boolean; removes a child from the flow |
| `constraints` | `{horizontal, vertical}` |

Grid keys: `gridColumns`, `gridRows`, `columnGap`, `rowGap`, `columnTracks`, `rowTracks`, `gridColumn`, `gridRow`, `gridColumnSpan`, `gridRowSpan`, `gridAlignH`, `gridAlignV`.

Track values: `120` (fixed px), `"1fr"` (share), `"auto"` (hug), or `{sizing, value}`.

## Layout commands

Use these only to convert or clean up existing layers:

```
run_command {command: "layout.add", params: {ids: [id], direction: "vertical"}}
run_command {command: "layout.suggest", params: {ids: [id]}}
run_command {command: "layout.remove", params: {ids: [id]}}
run_command {command: "layout.setTrack", params: {ids: [frameId], axis: "columns", index: 0, sizing: "fill"}}
run_command {command: "distribute.horizontal", params: {ids: [a, b, c], spacing: 16}}
run_command {command: "distribute.vertical", params: {ids: [a, b, c], spacing: 16}}
run_command {command: "align.left", params: {ids: [a, b]}}
```

Align commands: `align.left`, `align.hcenter`, `align.right`, `align.top`, `align.vcenter`, `align.bottom`.

## Tokens

The collection must exist before a variable can be created in it. Check once:

```
run_command {command: "variable.list"}
```

Create only what is missing:

```
run_command {command: "variable.createCollection", params: {name: "Color"}}
run_command {command: "variable.create", params: {
  collection: "Color", name: "text/primary", type: "color", value: "#111827"
}}
run_command {command: "variable.create", params: {
  collection: "Space", name: "space/16", type: "number", value: 16
}}
run_command {command: "style.create", params: {
  type: "text", name: "Body/Regular",
  value: {fontFamily: "Inter", fontStyle: "Regular", fontSize: 16, lineHeight: 24}
}}
```

Bind a color variable in a fill:

```json
{"fill": {"$var": "text/primary"}}
```

Apply a style:

```
run_command {command: "style.apply", params: {ids: [textId], style: "Body/Regular"}}
```

Or set `textStyle` directly in `set_properties`:

```json
{"ids": [textId], "props": {"textStyle": "Body/Regular"}}
```

## Components and variants

```
run_command {command: "component.create", params: {ids: [frameId]}}
run_command {command: "component.createMultiple", params: {ids: [a, b, c]}}
run_command {command: "component.combineVariants", params: {ids: [a, b, c]}}
run_command {command: "component.addVariant", params: {id: setId, property: "State", value: "Pressed"}}
run_command {command: "instance.create", params: {component: componentId, parent: rowId}}
run_command {command: "instance.place", params: {component: componentId, x: 320, y: 180}}
```

- `component.createMultiple` returns `{ids}`.
- `combineVariants` needs main components, not instances.
- `instance.create` inserts into an auto-layout parent.
- `instance.place` centers on a page point and inserts into the frame under it.
- Use `set_properties` on an instance only for overrides.

## Prototypes

Simple click navigation:

```
run_command {command: "proto.interaction.add", params: {id: buttonId, dest: targetScreenId}}
```

With trigger and transition:

```
run_command {command: "proto.interaction.add", params: {
  id: buttonId,
  trigger: {type: "onClick"},
  action: {type: "navigate"},
  dest: targetScreenId,
  transition: {type: "smartAnimate"},
  durationMs: 250,
  easing: "easeOut"
}}
```

Destinations must be existing frames or layers. Verify after adding.

## Verification

```
inspect_document {depth: 3, outline: true}
get_node {id: frameId, depth: 4, outline: true}
screenshot {ids: [frameId], scale: 1}
```

- `outline: true` keeps the response compact.
- `depth` limits tree size; increase only where needed.
- `screenshot` without `ids` captures the page; with `ids` captures those layers.
- `maxSize` defaults to 1600. Use `scale: 1` for a true-size mobile screen.

## Save

```
save_file {path: "<HOME>/Prototypes/<name>.figcraft"}
```

Only `~/Prototypes` is writable inside the Flatpak sandbox. Verify outside the app:

```
ls -l <HOME>/Prototypes/<name>.figcraft
```

## Failure handling

- `unknown command`: the command id is wrong. Use `list_commands {filter: "..."}` once, then correct it.
- `unknown property`: read the exact keys in `set_properties` docs; do not guess synonyms.
- Attached transport failure: the app may have applied the request before the reply was lost. Inspect before retrying.
- Batch step failure: earlier steps remain. Fix and rerun only the failed step.
- Save failure outside `~/Prototypes`: expected. Change the path.
