---
name: gamedev-assets
description: >
  Use when setting up asset loading, designing asset handles/registries,
  building offline asset processing tools, implementing hot reload, loading
  spritesheets or atlases, or deciding how to organize game asset directories.
---

# Rust Game Asset Pipeline

## Source vs runtime assets

Never load source assets at runtime. Convert them offline; ship only runtime
assets with the game.

| Type | Source (artist-edited) | Runtime (game loads) |
|---|---|---|
| Sprites | `.aseprite`, `.psd`, `.png` (large) | `.png` (atlased, power-of-two) |
| Audio | `.wav`, `.aiff` | `.ogg`, `.opus` |
| 3D models | `.blend`, `.fbx` | `.glb` (pre-processed) |
| Data | `.xlsx`, spreadsheet | `.ron`, `.json`, `.bin` |

```
assets-src/
  sprites/player.aseprite
  audio/jump.wav
  models/chest.blend

assets/                        <- what ships; what the game loads
  sprites/player.png
  sprites/player.atlas.ron
  audio/jump.ogg
  models/chest.glb
```

Build tools (scripts, `build.rs`, or a standalone `tools/` crate) own the
source-to-runtime conversion. The game binary never runs those tools.

## Asset handles

Use typed handles at runtime, not raw path strings.

```rust
#[derive(Clone, PartialEq, Eq, Hash)]
pub struct AssetHandle<T> {
    id: u32,
    _marker: PhantomData<T>,
}

pub struct AssetRegistry {
    textures: HashMap<AssetHandle<Texture>, Texture>,
    audio:    HashMap<AssetHandle<AudioClip>, AudioClip>,
}
```

Handles are `Copy`/`Clone` and cheap to pass around. The registry maps
handle to loaded data. Asset paths appear only during the loading phase;
gameplay code passes handles, never strings.

## Loading patterns

Load all assets before gameplay starts (startup or a dedicated loading
screen). Never load from disk mid-frame.

```rust
pub fn load_all(registry: &mut AssetRegistry, root: &Path) -> anyhow::Result<()> {
    registry.textures.insert(
        PLAYER_TEXTURE,
        load_texture(&root.join("sprites/player.png"))?,
    );
    // ...
    Ok(())
}
```

For large asset sets, use a background I/O thread with a completion channel:

```rust
let (tx, rx) = channel::<LoadResult>();
thread::spawn(move || {
    let tex = load_texture(&path);
    tx.send(LoadResult::Texture(handle, tex)).ok();
});
// Main thread polls rx each frame until loading is done.
```

### Hot reload (dev builds only)

```rust
#[cfg(debug_assertions)]
fn watch_assets(root: &Path, tx: Sender<ReloadEvent>) {
    // Use the `notify` crate to watch for file changes.
    // Send ReloadEvent on change; main loop reloads affected handle.
}
```

Gate hot reload behind `#[cfg(debug_assertions)]` or a feature flag so it
does not ship in release builds.

## Sprite atlases

Pack sprites into atlases to reduce draw calls and texture bind switches.

Atlas metadata lives in a sidecar file next to the texture:

```ron
// player.atlas.ron
AtlasLayout(
    texture: "sprites/player.png",
    sprites: {
        "idle_0":  (x: 0,   y: 0,  w: 32, h: 32),
        "idle_1":  (x: 32,  y: 0,  w: 32, h: 32),
        "run_0":   (x: 64,  y: 0,  w: 32, h: 32),
    },
)
```

Load the atlas texture and its `.ron`/`.json` sidecar together. Store UV
rects keyed by sprite name. Gameplay code requests a sprite by name and
receives a UV rect - no knowledge of atlas layout required.

## glTF / 3D models

Use the `gltf` crate to load `.glb` files. Extract into engine-native types
at load time; do not pass `gltf::Document` to gameplay systems.

```rust
fn load_mesh(path: &Path) -> anyhow::Result<Mesh> {
    let (document, buffers, _images) = gltf::import(path)?;
    let prim = document.meshes().next()
        .and_then(|m| m.primitives().next())
        .ok_or_else(|| anyhow!("no mesh"))?;
    let reader = prim.reader(|buf| Some(&buffers[buf.index()]));
    let positions: Vec<[f32; 3]> = reader.read_positions()
        .ok_or_else(|| anyhow!("no positions"))?.collect();
    Ok(Mesh { positions })
}
```

## Rules

- Runtime assets only: the game must not convert or process source assets at
  startup or mid-frame.
- Resolve all asset paths relative to an explicit asset root passed in at
  startup - never relative to the current working directory.
- No hardcoded absolute paths anywhere in asset loading code.
- Gameplay code must use typed `AssetHandle<T>`, not raw `&str` paths.
- Atlas, audio, and model loading happens once (startup or loading screen),
  not on demand during gameplay.
