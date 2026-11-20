---
name: gamedev-project-setup
description: >
  Use when creating a new Rust game project from scratch, evaluating the
  structure of an existing one, or deciding how to split code across crates.
  Covers project type recognition, workspace layout, crate responsibilities,
  asset directory conventions, shader placement, logging setup, and key
  architectural rules such as keeping renderer types out of game-core.
---

# Rust Game Project Setup

## Recognize the Project Type First

Before generating any structure, identify what kind of project this is:

- **Custom engine game** - owns its own renderer (wgpu), windowing (winit), and ECS. Use the full crate split below.
- **Bevy game** - Bevy provides engine, ECS, and asset pipeline. Simpler crate split; see `gamedev-bevy` skill instead.
- **Library crate** - ships a reusable game component (physics, audio, etc.). Single crate, no `game-app`.
- **Example app** - minimal standalone demo. Flat layout, no workspace split unless demonstrating one.

When in doubt, ask. Never assume Bevy unless `bevy` is already in `Cargo.toml`.

## Preferred Workspace Layout

Use a `crates/` subdirectory for all crates. The root `Cargo.toml` is a
workspace manifest only - it contains no `[lib]` or `[bin]` sections.

```
my-game/
  Cargo.toml          # [workspace] only
  crates/
    game-core/        # ECS, game logic, no wgpu
    game-render/      # wgpu renderer
    game-audio/       # rodio/cpal audio
    game-platform/    # winit, OS integration
    game-assets/      # asset loading, handles
    game-app/         # main entry point, glues everything
  assets/
    textures/
    models/
    audio/
    fonts/
    shaders/
  examples/
  tools/
```

Keep all crates inside `crates/`. Do not place them at the workspace root
alongside `Cargo.toml` - that pattern makes paths ambiguous as the project
grows.

## Crate Responsibilities

**game-core**
- ECS world, systems, components, game logic
- No renderer types. No wgpu. No winit.
- May depend on: `glam`, `hecs`/`legion`, `serde`, `tracing`
- Exposes abstract handles (e.g. `TextureHandle(u32)`) not concrete GPU objects

**game-render**
- All wgpu code lives here
- Reads abstract handles from game-core, produces frames
- May depend on: `game-core`, `game-assets`, `wgpu`, `wgsl` tools
- Never exposes `wgpu::` types in its public API if other crates consume it

**game-audio**
- Audio playback via `rodio` or `cpal`
- Receives abstract sound events or handles from game-core
- Does not import game-render

**game-platform**
- Window creation and event loop (`winit`)
- OS-specific integration (file dialogs, clipboard, etc.)
- May depend on: `game-core`, `game-render`, `game-audio`
- Isolates `winit::event::Event` so the rest of the codebase does not leak it

**game-assets**
- Asset loading, file I/O, hot-reload logic
- Defines `AssetHandle<T>` or similar
- No wgpu types; produces raw bytes or decoded structs

**game-app**
- Binary crate (`src/main.rs`)
- Wires all other crates together
- Owns top-level `tracing` subscriber setup
- Uses `anyhow::Result` at the top level - this is the only appropriate place

## Asset Directory Layout

```
assets/
  textures/    # .png, .ktx2, .dds
  models/      # .gltf, .glb, .obj
  audio/       # .ogg, .wav, .flac
  fonts/       # .ttf, .otf
  shaders/     # runtime WGSL/GLSL shaders loaded from disk
```

Shader placement rule:
- **Runtime shaders** loaded from disk at startup: `assets/shaders/`
- **Embedded shaders** compiled into the binary via `include_str!`: `crates/game-render/src/shaders/`

Do not mix these. If a shader is ever hot-reloaded, it belongs in `assets/shaders/`.

## Examples and Tools

`examples/` - runnable examples that compile as part of CI. Each example must
be self-contained enough to run with `cargo run --example <name>`. Examples
demonstrate features, not internal implementation details.

`tools/` - offline tooling: asset converters, map editors, sprite packers.
These are separate binaries. They may share `game-assets` and `game-core` but
must not depend on `game-render` unless they render previews.

## Logging and Tracing Setup

Use the `tracing` crate throughout. Set up the subscriber once in `game-app/src/main.rs`:

```rust
use tracing_subscriber::{fmt, EnvFilter};

fn main() {
    fmt()
        .with_env_filter(EnvFilter::from_default_env())
        .init();
    // ...
}
```

- Library crates (`game-core`, `game-render`, etc.) only call `tracing::info!`, `tracing::warn!`, etc. - never configure subscribers.
- Use `RUST_LOG=my_game=debug` for filtering during development.
- For async or Bevy projects, configure the subscriber before any async runtime starts.

## Feature Flags

Define features in the relevant crate, not in `game-app` alone.

Common patterns:

```toml
# game-core/Cargo.toml
[features]
default = []
dev-tools = ["dep:egui"]        # enables in-game debug UI
profiling = ["dep:puffin"]      # enables puffin profiler hooks
```

```toml
# game-app/Cargo.toml
[features]
default = []
dev-tools = ["game-core/dev-tools", "game-render/dev-tools"]
```

- Gate debug overlays, frame time graphs, and entity inspectors behind `dev-tools`.
- Gate profiling instrumentation behind `profiling`.
- Platform-specific features (e.g. `android`, `web`) get their own flags or separate crates.

## Architectural Rules

**Never leak renderer types into game-core.**
If `game-core` imports `wgpu`, the abstraction boundary is broken. Use handle
types (newtypes over `u32` or `u64`) to refer to GPU resources from logic code.

**Keep platform-specific code behind cfg or separate crates.**
Acceptable:
```rust
#[cfg(target_os = "windows")]
fn set_dpi_aware() { ... }
```
Not acceptable: sprinkling `#[cfg(target_os = ...)]` blocks throughout
`game-core`. Move OS-specific code into `game-platform` or a platform subcrate.

**Crate dependency direction (no cycles):**
```
game-app -> game-platform -> game-render -> game-assets -> game-core
                          -> game-audio -> game-core
```
`game-core` has no game-* dependencies. Violations are build errors - enforce with workspace structure.
