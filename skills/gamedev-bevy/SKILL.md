---
name: gamedev-bevy
description: Use ONLY when the project already uses Bevy (bevy in Cargo.toml) or the user explicitly asks about Bevy. Do not trigger for custom wgpu/winit/ECS projects. Use when working with Bevy plugins, components, systems, states, the Bevy asset server, schedules, or events.
---

# Bevy Game Development

## When to Use This Skill

Trigger conditions:
- `bevy` appears in `Cargo.toml` (dependencies or workspace)
- User explicitly asks about Bevy APIs, systems, or plugins

Do NOT trigger for:
- Custom wgpu/winit projects - use `gamedev-wgpu-rendering` and `gamedev-winit-loop` instead
- Raw ECS projects without Bevy - use `gamedev-ecs` instead
- Do not suggest migrating a working custom engine to Bevy

---

## Plugins: the Unit of Organization

Every feature area is a plugin. Do not dump everything into `main`.

```rust
pub struct PlayerPlugin;

impl Plugin for PlayerPlugin {
    fn build(&self, app: &mut App) {
        app
            .add_systems(Startup, spawn_player)
            .add_systems(Update, (move_player, animate_player).chain())
            .add_event::<PlayerJumped>();
    }
}
```

Register in `main`:

```rust
app.add_plugins((DefaultPlugins, PlayerPlugin, EnemyPlugin, UiPlugin));
```

Use `DefaultPlugins` for standard setup (window, input, asset server, audio, rendering).
Use `MinimalPlugins` for headless/server contexts.

---

## Components and Resources

```rust
// Per-entity data
#[derive(Component)]
struct Velocity(Vec2);

#[derive(Component)]
struct Health { current: f32, max: f32 }

// Marker component - no data needed
#[derive(Component)]
struct Player;

// Global singleton
#[derive(Resource)]
struct GameConfig { gravity: f32 }

// Bundle groups components for spawning
#[derive(Bundle)]
struct PlayerBundle {
    velocity: Velocity,
    health: Health,
    marker: Player,
    sprite: SpriteBundle,
}
```

Spawn with a bundle:

```rust
commands.spawn(PlayerBundle { ... });
```

---

## Systems and Queries

Systems are plain functions. Bevy injects parameters automatically.

```rust
fn move_player(
    mut query: Query<(&mut Transform, &Velocity), With<Player>>,
    time: Res<Time>,
) {
    for (mut transform, velocity) in &mut query {
        transform.translation += velocity.0.extend(0.0) * time.delta_seconds();
    }
}
```

Query filters:
- `With<T>` / `Without<T>` - filter by presence
- `Changed<T>` - only entities where T changed this frame
- `Added<T>` - only entities where T was added this frame

Multi-query in one system: use `ParamSet` if queries would conflict.

---

## Schedules: Where Systems Run

| Schedule | When |
|---|---|
| `Startup` | Once at app start |
| `Update` | Every frame |
| `FixedUpdate` | Fixed timestep (physics) |
| `PostUpdate` | After Update, before rendering |

Order systems within a schedule:

```rust
app.add_systems(Update, (
    read_input,
    apply_movement.after(read_input),
    sync_camera.after(apply_movement),
));
```

Or use `SystemSet` for coarser ordering:

```rust
#[derive(SystemSet, Debug, Clone, PartialEq, Eq, Hash)]
enum GameSet { Input, Movement, Camera }

app.configure_sets(Update, (
    GameSet::Input,
    GameSet::Movement.after(GameSet::Input),
    GameSet::Camera.after(GameSet::Movement),
));
```

---

## States

```rust
#[derive(States, Debug, Clone, PartialEq, Eq, Hash, Default)]
enum AppState { #[default] Loading, MainMenu, InGame, Paused }

app.init_state::<AppState>();

// Systems run only in a specific state
app.add_systems(Update, run_gameplay.run_if(in_state(AppState::InGame)));

// Transition
fn pause_game(mut next: ResMut<NextState<AppState>>) {
    next.set(AppState::Paused);
}
```

Use `OnEnter` / `OnExit` schedules for setup/teardown at state boundaries.

---

## Asset Server

```rust
fn load_assets(mut commands: Commands, server: Res<AssetServer>) {
    let handle: Handle<Image> = server.load("sprites/player.png");
    commands.insert_resource(PlayerSprite(handle));
}
```

Check load state before using:

```rust
fn check_loaded(
    server: Res<AssetServer>,
    handle: Res<PlayerSprite>,
    mut next: ResMut<NextState<AppState>>,
) {
    if server.load_state(&handle.0) == LoadState::Loaded {
        next.set(AppState::InGame);
    }
}
```

Asset paths are relative to the `assets/` folder at the crate root.

---

## Events

```rust
#[derive(Event)]
struct PlayerJumped { height: f32 }

// Send
fn jump(mut writer: EventWriter<PlayerJumped>) {
    writer.send(PlayerJumped { height: 2.0 });
}

// Receive
fn on_jump(mut reader: EventReader<PlayerJumped>) {
    for event in reader.read() {
        println!("Jumped: {}", event.height);
    }
}
```

Events are cleared automatically (double-buffered, survive one frame).
For persistent events use `EventReader::read` before the next send cycle.

---

## Recommended Crates

| Need | Crate |
|---|---|
| 2D physics | `bevy_rapier2d` |
| 3D physics | `bevy_rapier3d` |
| Debug UI / inspector | `bevy-inspector-egui` |
| EGUI panels | `bevy_egui` |
| Tilemap | `bevy_ecs_tilemap` |
| Animation state machine | `bevy_ecs_ldtk` or custom |

Prefer Bevy's built-in solutions first. Reach for third-party crates only when the built-in is insufficient.

---

## Rules

- Do not re-implement what Bevy already provides (timers, transforms, asset loading).
- Keep plugins focused: one feature area per plugin.
- Use `FixedUpdate` for anything that must be deterministic (physics, game logic).
- Avoid `Local<T>` overuse - prefer `Resource` for shared state.
- Do not suggest replacing a custom wgpu/winit engine with Bevy unless the user asks.
