---
name: gamedev-physics
description: Use when implementing collision detection, physics integration (AABB, swept collision, or Rapier), fixed timestep loops, character controllers, or physics-to-render interpolation in a Rust game.
---

# Physics, Collision, and Movement for Rust Games

## Fixed Timestep: The Most Important Rule

Physics must never run at variable framerate. Accumulate elapsed time, advance in fixed increments, pass the remainder to the renderer as an interpolation factor.

```rust
const FIXED_STEP: f32 = 1.0 / 60.0;

accumulator += delta_time;
while accumulator >= FIXED_STEP {
    physics_world.step(FIXED_STEP);
    accumulator -= FIXED_STEP;
}

let alpha = accumulator / FIXED_STEP; // 0..1, used for render interpolation
```

If `delta_time` is huge (window minimized, debugger paused), cap it before accumulating to avoid a spiral-of-death:

```rust
let delta_time = delta_time.min(0.25);
```

---

## Custom Physics (No Rapier)

### AABB Collision

Axis-aligned bounding boxes are the right starting point. Fast broadphase, trivial to debug.

```rust
pub struct Aabb {
    pub min: Vec2,
    pub max: Vec2,
}

impl Aabb {
    pub fn intersects(&self, other: &Aabb) -> bool {
        self.max.x > other.min.x && self.min.x < other.max.x
            && self.max.y > other.min.y && self.min.y < other.max.y
    }

    /// Returns the time of first contact (0..1) along the velocity vector,
    /// or None if no collision occurs this step.
    pub fn swept(&self, velocity: Vec2, other: &Aabb) -> Option<f32> { ... }
}
```

### Swept AABB

Expand the static box by the moving box's half-extents. Cast a ray from the moving box's center along its velocity. The ray's hit time is the collision time.

Use swept AABB to prevent tunneling at high speeds. Return the hit time `t` (0..1), then move the entity to `position + velocity * t`, then resolve.

### Tile Grid Collision

Test the four corners of the moving AABB against the tile grid. Correct, cheap, and sufficient for most 2D platformers.

1. Move on X axis.
2. Test all four corners against tile grid.
3. Push out on X.
4. Move on Y axis.
5. Test all four corners against tile grid.
6. Push out on Y.

Resolving X and Y separately is the platformer feel people expect.

### Character Controller Pattern

```rust
pub fn move_and_collide(
    pos: &mut Vec2,
    vel: &mut Vec2,
    aabb_half: Vec2,
    tiles: &TileGrid,
    dt: f32,
) {
    pos.x += vel.x * dt;
    if let Some(correction) = tiles.resolve_x(*pos, aabb_half) {
        pos.x += correction;
        vel.x = 0.0;
    }

    pos.y += vel.y * dt;
    if let Some(correction) = tiles.resolve_y(*pos, aabb_half) {
        pos.y += correction;
        vel.y = 0.0;
        // set grounded flag here if correction pushed upward
    }
}
```

---

## Rapier Integration

Use Rapier for games that need joints, complex shapes, or rigid body simulation. Use custom AABB for platformers and top-down shooters.

**Resource layout:**

```rust
pub struct PhysicsWorld {
    pub rigid_body_set: RigidBodySet,
    pub collider_set: ColliderSet,
    pub pipeline: PhysicsPipeline,
    // gravity, integration_parameters, island_manager, etc.
}
```

Store these as ECS resources, not as fields on individual entities.

**Handles as components:**

```rust
// Gameplay component - just the handle
pub struct PhysicsBody(pub RigidBodyHandle);

// Do not store RigidBody directly in ECS. Ever.
```

**Sync step (runs after PhysicsPipeline::step):**

```rust
fn sync_physics_to_ecs(
    physics: Res<PhysicsWorld>,
    mut query: Query<(&PhysicsBody, &mut Position, &mut Rotation)>,
) {
    for (body_handle, mut pos, mut rot) in query.iter_mut() {
        let body = &physics.rigid_body_set[body_handle.0];
        let t = body.position();
        pos.x = t.translation.x;
        pos.y = t.translation.y;
        rot.angle = t.rotation.angle();
    }
}
```

Never let gameplay systems call into `rigid_body_set` directly. Route reads through `Position`/`Rotation` components.

---

## Physics-to-Render Interpolation

Store two copies of the physics state per entity.

```rust
pub struct PhysicsState {
    pub position: Vec2,
    pub rotation: f32,
    pub prev_position: Vec2,
    pub prev_rotation: f32,
}
```

Before each physics step, copy current into prev. After the step, sync from Rapier or integrate manually.

The renderer reads:

```rust
let render_pos = prev_position.lerp(position, alpha);
let render_rot = lerp_angle(prev_rotation, rotation, alpha);
```

This gives smooth rendering at 144 Hz even with a 60 Hz physics tick.

---

## Collision Events

Do not apply game effects inside the collision detection loop. Separate detection from response.

```rust
pub struct CollisionEvent {
    pub entity_a: Entity,
    pub entity_b: Entity,
    pub normal: Vec2,
    pub depth: f32,
}
```

Physics system emits `CollisionEvent`. Damage, sound, and particle systems consume it. This keeps physics code free of game logic.

---

## Rules

- Physics never runs at variable framerate. No exceptions.
- Do not call `physics_world.step()` inside the render loop.
- Cap delta time before accumulation to avoid spiral-of-death.
- Rapier handles (`RigidBodyHandle`, `ColliderHandle`) live in ECS components. Rapier types do not.
- Sync Rapier state to `Position`/`Rotation` components after every step.
- Store `prev_position` alongside `position` for render interpolation.
- Physics systems belong in `FixedUpdate`, not `Update`.
- Resolve X and Y axis separately in character controllers.
