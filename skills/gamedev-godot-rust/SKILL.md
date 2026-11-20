---
name: gamedev-godot-rust
description: Use ONLY when the project uses Godot with Rust (gdext or gdnative in Cargo.toml, or .gdextension file present). Do not trigger for pure Rust/wgpu projects. Use when working with GodotClass, #[func], #[export], signals, or the gdext API.
---

# Godot + Rust with gdext

## When to Use This Skill

Trigger conditions:
- `gdext` or `godot` (the gdext crate) appears in `Cargo.toml`
- A `.gdextension` file is present in the project
- User explicitly asks about Godot-Rust integration

Do NOT trigger for:
- Pure Rust / wgpu projects with no Godot
- Projects using gdnative unless explicitly stated (gdnative is Godot 3 / legacy)

Default to **gdext** (Godot 4). Only use gdnative patterns if the project already uses it.

---

## Crate Setup

`Cargo.toml`:

```toml
[lib]
crate-type = ["cdylib"]

[dependencies]
godot = { git = "https://github.com/godot-rust/gdext", branch = "master" }
```

`lib.rs`:

```rust
use godot::prelude::*;

struct MyExtension;

#[gdextension]
unsafe impl ExtensionLibrary for MyExtension {}
```

---

## Defining a Godot Class

```rust
use godot::prelude::*;
use godot::classes::{Node, INode};

#[derive(GodotClass)]
#[class(base=Node)]
pub struct MyNode {
    base: Base<Node>,
    speed: f32,
}

#[godot_api]
impl INode for MyNode {
    fn init(base: Base<Node>) -> Self {
        MyNode { base, speed: 100.0 }
    }

    fn ready(&mut self) {
        godot_print!("MyNode ready");
    }

    fn process(&mut self, delta: f64) {
        // called every frame
        let _ = delta;
    }
}
```

Match the `I*` trait to the base class: `INode2D`, `INode3D`, `ICharacterBody2D`, etc.

---

## Exposing Methods and Properties

```rust
#[godot_api]
impl MyNode {
    // Callable from GDScript
    #[func]
    fn jump(&mut self) {
        godot_print!("jump!");
    }

    // Visible in the Godot editor inspector
    #[export]
    fn get_speed(&self) -> f32 {
        self.speed
    }

    #[export]
    fn set_speed(&mut self, value: f32) {
        self.speed = value;
    }
}
```

For simple exported fields, use `#[export]` directly on the struct field (gdext supports this):

```rust
#[derive(GodotClass)]
#[class(base=Node)]
pub struct MyNode {
    base: Base<Node>,
    #[export]
    speed: f32,
}
```

---

## Signals

Define and emit signals:

```rust
#[godot_api]
impl MyNode {
    #[signal]
    fn player_died();

    #[signal]
    fn score_changed(new_score: i64);
}

// Emit
fn die(&mut self) {
    self.base_mut().emit_signal("player_died", &[]);
}

fn add_score(&mut self, amount: i64) {
    self.base_mut().emit_signal("score_changed", &[amount.to_variant()]);
}
```

Connect signals from GDScript as normal - no special setup needed on the Rust side.

---

## Getting Nodes and Calling Methods

```rust
// Typed node access
let label = self.base().get_node_as::<Label>("UI/ScoreLabel");
label.set_text("Score: 0");

// Untyped call (use sparingly)
self.base_mut().call("some_gdscript_method", &[42_i64.to_variant()]);
```

Cache node references in `ready` where possible rather than calling `get_node_as` every frame.

---

## Data Exchange: Rust <-> GDScript

Preferred pattern - thin Rust wrapper, GDScript drives the scene:

- Keep scene structure, animations, and UI wiring in GDScript / the editor.
- Keep algorithms, data processing, and heavy logic in Rust.
- Expose a clean API surface via `#[func]` and `#[export]`.

Avoid:
- Putting Godot types (`Gd<T>`, `NodePath`) deep into pure Rust logic modules.
- Trying to replicate the Godot scene tree in Rust data structures.

---

## Build Setup

`Cargo.toml` must produce a `cdylib`:

```toml
[lib]
crate-type = ["cdylib"]
```

`.gdextension` file (place in the Godot project root or `res://`):

```ini
[configuration]
entry_symbol = "gdext_rust_init"
compatibility_minimum = 4.1

[libraries]
linux.debug.x86_64 = "res://../rust/target/debug/libmy_game.so"
linux.release.x86_64 = "res://../rust/target/release/libmy_game.so"
windows.debug.x86_64 = "res://../rust/target/debug/my_game.dll"
windows.release.x86_64 = "res://../rust/target/release/my_game.dll"
```

Adjust paths to match your workspace layout. Rebuild Rust before running the Godot editor after changes.

---

## Common Patterns

Accessing a sibling node:

```rust
let parent = self.base().get_parent().unwrap();
let sibling = parent.get_node_as::<AnimationPlayer>("AnimationPlayer");
sibling.play_ex().name("jump").done();
```

One-shot timer:

```rust
fn start_timer(&mut self) {
    let mut timer = self.base_mut().get_tree().unwrap()
        .create_timer(2.0).unwrap();
    timer.connect("timeout", self.base().callable("on_timeout"));
}

#[godot_api]
impl MyNode {
    #[func]
    fn on_timeout(&mut self) { ... }
}
```

---

## Rules

- Use gdext (Godot 4), not gdnative (Godot 3), unless the project already uses gdnative.
- Keep Godot types at the boundary - do not leak `Gd<T>` into interior Rust logic.
- Let Godot own physics and rendering. Use Rust for logic, state machines, algorithms.
- Prefer `#[export]` on struct fields over manual getter/setter pairs when no side effects are needed.
- Always check for `Option`/`Result` when calling `get_node_as` - missing nodes crash at runtime.
