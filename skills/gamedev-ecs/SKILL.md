---
name: gamedev-ecs
description: Use when designing ECS component layouts, system ordering, event systems, deferred spawning/despawning, fixed vs variable update schedules, or deciding how game world data flows to the renderer. Use for both custom ECS and library ECS (hecs, legion).
---

# ECS Architecture for Rust Game Engines

## Core Concepts

**Components** are plain data structs. No behavior, no references to other entities, no GPU resources.

**Resources** are global singletons injected as system parameters: renderer config, input state, elapsed time.

**Systems** are functions that query components and/or resources. Keep them small and single-purpose.

**Schedules** are ordered sets of systems. The main schedules are:
- `FixedUpdate` - deterministic physics/simulation tick
- `Update` - per-frame gameplay and animation
- `RenderExtract` - copy game state into renderer-owned data
- `Render` - GPU work

---

## Separation of Concerns: The Most Important Rule

Do NOT put wgpu resources in gameplay components:

```rust
// WRONG - GPU state in ECS
struct Sprite {
    texture: wgpu::Texture,      // no
    bind_group: wgpu::BindGroup, // no
    buffer: wgpu::Buffer,        // no
}

// RIGHT - logical game state only
struct Position { pub x: f32, pub y: f32 }
struct Velocity { pub x: f32, pub y: f32 }
struct SpriteIndex(pub u32);
struct Health { pub current: i32, pub max: i32 }
```

GPU state lives in the renderer. The ECS holds logical game state. The render extract step bridges them.

---

## Render Extract Pattern

The `RenderExtractSystem` copies ECS state into renderer-owned data structures each frame.

```rust
// Gameplay components - live in ECS
struct Position { x: f32, y: f32 }
struct SpriteIndex(u32);

// Extracted render data - owned by the renderer, not ECS
struct ExtractedSprite {
    transform: Mat4,
    sprite_index: u32,
    layer: u8,
}

// RenderExtractSystem: runs after Update, before Render
fn render_extract_system(
    query: Query<(&Position, &SpriteIndex)>,
    mut render_data: ResMut<ExtractedSpriteList>,
) {
    render_data.sprites.clear();
    for (pos, sprite) in query.iter() {
        render_data.sprites.push(ExtractedSprite {
            transform: Mat4::from_translation(vec3(pos.x, pos.y, 0.0)),
            sprite_index: sprite.0,
            layer: 0,
        });
    }
}
```

Never let the render system reach back into the ECS. It reads from extracted data only.

---

## System Ordering

```
InputSystem          // read raw InputState, emit typed input events
MovementSystem       // apply Velocity to Position
PhysicsSystem        // collision detection, fixed timestep only
AnimationSystem      // update AnimationState from velocity/events
AudioEventSystem     // react to game events, push audio commands
RenderExtractSystem  // copy ECS state -> ExtractedSpriteList etc.
RenderSystem         // GPU work, reads extracted data, no ECS access
```

Systems in `FixedUpdate`:
- `PhysicsSystem`, `MovementSystem` (simulation)

Systems in `Update`:
- `InputSystem`, `AnimationSystem`, `AudioEventSystem`, `RenderExtractSystem`

`RenderSystem` runs after extract, outside the ECS schedule.

---

## Events

Use typed event queues for inter-system communication. Do not use `std::sync::mpsc` channels for game events.

```rust
struct JumpEvent { entity: Entity }
struct DamageEvent { target: Entity, amount: i32, source: Entity }

// Systems write to event queues
fn player_system(input: Res<ActionState>, mut jump_events: EventWriter<JumpEvent>) {
    if input.just_pressed(Action::Jump) {
        jump_events.send(JumpEvent { entity: player });
    }
}

// Other systems read from event queues
fn animation_system(mut jump_events: EventReader<JumpEvent>, ...) {
    for ev in jump_events.read() { ... }
}
```

Clear events at end of frame, or use double-buffered event queues to allow one-frame lag between writer and reader.

---

## Deferred Mutation (Commands)

Spawning and despawning during iteration corrupts queries. Defer all structural changes.

```rust
// Queue commands during system execution
fn enemy_death_system(
    query: Query<(Entity, &Health)>,
    mut commands: Commands,
) {
    for (entity, health) in query.iter() {
        if health.current <= 0 {
            commands.despawn(entity);           // deferred
            commands.spawn(DeathParticles { .. }); // deferred
        }
    }
}
// Commands are applied between systems, not mid-iteration
```

Apply command queues at defined sync points between systems, not inside the hot loop.

---

## Fixed vs Variable Update

| Concern | Schedule | Timestep |
|---|---|---|
| Physics, collision | FixedUpdate | Fixed (e.g. 1/60 s) |
| Game simulation | FixedUpdate | Fixed |
| Animation blending | Update | Variable (delta_time) |
| Camera smoothing | Update | Variable |
| Input reading | Update | Variable |
| Render extract | Update | Variable |

Store a `fixed_timestep_alpha` (0..1) for interpolating between the previous and current physics state during rendering.

---

## Rules

- Components are data, not objects. No methods that reach into other components or resources.
- Resources are not global singletons. Inject them as system parameters; do not use `lazy_static` or `OnceCell` for game state.
- No GPU resources (`wgpu::*`) in ECS components. Ever.
- Keep system functions small. One system, one responsibility.
- Prefer many small components over large monolithic components (prefer composition).
- Use marker components (`struct Enemy;`, `struct Player;`) for entity classification queries.
