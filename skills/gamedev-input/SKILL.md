---
name: gamedev-input
description: Use when setting up input handling, designing action maps, rebindable controls, gamepad support, mouse delta handling, input buffering, or deciding how raw winit events should flow to gameplay code.
---

# Input Handling for Rust Game Engines

## Architecture

Raw input flows through three layers:

```
winit events -> InputState -> Actions -> Gameplay systems
```

Never let gameplay code touch raw keycodes or winit events directly.

---

## InputState

Collects raw events from winit each frame. Updated in the event loop before any systems run.

```rust
pub struct InputState {
    pub keys_down: HashSet<KeyCode>,
    pub keys_just_pressed: HashSet<KeyCode>,
    pub keys_just_released: HashSet<KeyCode>,
    pub mouse_position: Vec2,
    pub mouse_delta: Vec2,
    pub mouse_buttons: HashSet<MouseButton>,
    pub scroll_delta: Vec2,
    pub gamepad_axes: HashMap<GamepadAxis, f32>,
    pub gamepad_buttons: HashSet<GamepadButton>,
    pub gamepad_buttons_just_pressed: HashSet<GamepadButton>,
}

impl InputState {
    /// Call at the end of each frame, after all systems have run.
    pub fn end_frame(&mut self) {
        self.keys_just_pressed.clear();
        self.keys_just_released.clear();
        self.mouse_delta = Vec2::ZERO;
        self.scroll_delta = Vec2::ZERO;
        self.gamepad_buttons_just_pressed.clear();
    }
}
```

---

## Actions

Actions are named game intents. Gameplay code checks actions, not raw inputs.

```rust
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Action {
    Jump,
    Attack,
    Dodge,
    MoveLeft,
    MoveRight,
    MoveUp,
    MoveDown,
    Pause,
    Interact,
}

pub struct InputBindings {
    pub key_actions: HashMap<KeyCode, Action>,
    pub gamepad_button_actions: HashMap<GamepadButton, Action>,
}
```

Load `InputBindings` from a config file at startup. Users can rebind controls without recompiling.

---

## ActionState

Derived from `InputState` + `InputBindings` each frame. This is what gameplay systems read.

```rust
pub struct ActionState {
    pressed: HashSet<Action>,
    just_pressed: HashSet<Action>,
    just_released: HashSet<Action>,
}

impl ActionState {
    pub fn is_pressed(&self, action: Action) -> bool {
        self.pressed.contains(&action)
    }
    pub fn just_pressed(&self, action: Action) -> bool {
        self.just_pressed.contains(&action)
    }
    pub fn just_released(&self, action: Action) -> bool {
        self.just_released.contains(&action)
    }
}
```

Build `ActionState` in an `InputSystem` that runs first in the frame. All other systems read the snapshot - they do not access `InputState` directly.

---

## Rules

- Gameplay logic checks `ActionState`, never `KeyCode` or `MouseButton`.
- `InputState.end_frame()` runs after all systems, before the next event poll.
- Systems read the `ActionState` snapshot built at frame start; they do not call `end_frame` themselves.
- `InputBindings` is data - load it from config, allow runtime rebinding.
- One action can be triggered by keyboard or gamepad - map both in `InputBindings`.

---

## Gamepad Support

Process gamepad axes through a deadzone before using them.

```rust
fn apply_deadzone(value: f32, deadzone: f32) -> f32 {
    if value.abs() < deadzone {
        0.0
    } else {
        // Rescale so the usable range starts at 0, not at deadzone
        let sign = value.signum();
        sign * (value.abs() - deadzone) / (1.0 - deadzone)
    }
}
```

Typical deadzone: 0.15-0.20. Store as a configurable value, not a magic constant.

Map axes to movement actions separately from buttons. A left-stick X axis below -0.5 can emit `MoveLeft`; above +0.5 emits `MoveRight`. The threshold is part of `InputBindings`.

---

## Mouse Input

Two distinct use cases:

| Use case | Source | Notes |
|---|---|---|
| UI cursor, aim reticle | `WindowEvent::CursorMoved` (absolute position) | OS-accelerated, fine for UI |
| Camera rotation, FPS look | `DeviceEvent::MouseMotion` (raw delta) | Bypasses OS acceleration |

For first-person or camera-control:
- Use `DeviceEvent::MouseMotion` for the raw delta. Store in `InputState.mouse_delta`.
- Call `window.set_cursor_grab(CursorGrabMode::Locked)` and `window.set_cursor_visible(false)` when entering look mode.
- Release the grab on focus loss (`WindowEvent::Focused(false)`).

Do not use `CursorMoved` for camera rotation - OS mouse acceleration makes it feel wrong at low sensitivity.

---

## Input Buffering (Optional)

For action games or fighting games where input timing matters:

```rust
pub struct InputBuffer {
    // Ring buffer of (action, frame_number) pairs
    history: VecDeque<(Action, u64)>,
    capacity: usize,
}

impl InputBuffer {
    /// Returns true if `action` was pressed within the last `window_frames` frames.
    pub fn recently_pressed(&self, action: Action, current_frame: u64, window_frames: u64) -> bool {
        self.history.iter().any(|(a, frame)| {
            *a == action && current_frame.saturating_sub(*frame) <= window_frames
        })
    }
}
```

Push to the buffer in `InputSystem` when an action is `just_pressed`. Use `recently_pressed` in gameplay systems to implement forgiving input windows (e.g., jump pressed 3 frames ago still triggers a buffered jump).

---

## Common Commands

```sh
# Run the input test example
cargo run --example input-test

# Run with gamepad debug output
RUST_LOG=input=debug cargo run --example input-test
```

---

## Common Mistakes

- Checking `KeyCode::Space` in a movement system. Use `Action::Jump` instead.
- Forgetting to call `end_frame()`, causing `just_pressed` to stay true forever.
- Using `CursorMoved` for camera rotation. Use `DeviceEvent::MouseMotion`.
- Hardcoding bindings. Put them in `InputBindings` and load from config.
- Applying raw axis values without deadzone - stick drift will affect gameplay.
