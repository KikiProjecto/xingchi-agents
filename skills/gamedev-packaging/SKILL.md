---
name: gamedev-packaging
description: Use when preparing a Rust game for distribution, setting up release builds, bundling assets, creating Linux/Windows/macOS packages, or configuring asset path resolution for deployed executables.
---

# Rust Game Packaging

---

## Asset Path Resolution (Most Important Rule)

**Never resolve assets relative to the current working directory.**

`cargo run` sets the working directory to the workspace root. A shipped
executable has no such guarantee. Always resolve relative to the executable.

```rust
pub fn asset_root() -> PathBuf {
    let exe = std::env::current_exe().expect("cannot locate executable");
    exe.parent()
        .expect("executable has no parent directory")
        .join("assets")
}
```

Use this function everywhere you open an asset file. Never use `"assets/..."` as
a bare relative path in production code.

---

## Release Build Profile

```toml
[profile.release]
opt-level = 3
lto = "thin"
codegen-units = 1
strip = true
```

- `lto = "thin"` gives most of the link-time optimization benefit without the
  full compile time cost of `lto = true`.
- `strip = true` removes debug symbols from the binary. Reduces size
  significantly. If you need symbols for a crash reporter, strip in a post-build
  step instead and keep the unstripped binary separately.
- `codegen-units = 1` allows the compiler to optimize across the whole crate.

---

## Distributed Package Layout

Every platform uses the same layout:

```
my-game-<platform>/
  my-game           # executable (my-game.exe on Windows)
  assets/           # all runtime assets
  README.txt
```

The executable and the `assets/` directory must be siblings. The `asset_root()`
function above depends on this.

Do not include dev-only assets, editor tooling, or source files in the
distributed package.

---

## Linux Packaging

**Fully static (simplest, most portable):**

```sh
rustup target add x86_64-unknown-linux-musl
cargo build --release --target x86_64-unknown-linux-musl
```

Note: musl does not work with dynamically loaded Vulkan/OpenGL drivers. If you
use wgpu with Vulkan, prefer dynamic linking against a known glibc version.

**Dynamic linking (wgpu/Vulkan compatible):**

Build normally with `x86_64-unknown-linux-gnu`. Ship with the expectation that
the user has:
- glibc (virtually universal)
- libGL or Vulkan loader (`libvulkan.so.1`)
- libasound (ALSA, for audio)

List your actual runtime dependencies with:
```sh
ldd target/release/my-game
```

**AppImage (recommended for broad distro support):**
Bundles all non-system libs. Runs on most Linux distros without installation.

```sh
cargo install cargo-appimage
cargo appimage
```

Or build manually with `appimagetool`. AppImages are a single executable file
and are the closest Linux equivalent to a macOS .app bundle.

---

## Windows Packaging

Target: `x86_64-pc-windows-msvc` (preferred) or `x86_64-pc-windows-gnu`.

Bundle layout:
```
my-game-windows/
  my-game.exe
  assets/
```

If using wgpu with the Vulkan backend and distributing the Vulkan validation
layers or runtime: include `vulkan-1.dll`. For most wgpu setups this is not
needed as wgpu falls back to DX12 or DX11.

**Installer (optional):**
- `cargo-wix`: generates an MSI from a WiX template. Good for Steam or direct
  distribution that expects a standard installer.
- NSIS: more flexible, wider tooling support, requires a .nsi script.

For indie distribution (itch.io, direct download), a plain .zip is usually
sufficient.

---

## macOS Packaging

Create a `.app` bundle:

```
MyGame.app/
  Contents/
    Info.plist
    MacOS/
      my-game           # executable
    Resources/
      assets/           # runtime assets
```

Adjust `asset_root()` to handle the bundle layout:

```rust
pub fn asset_root() -> PathBuf {
    let exe = std::env::current_exe().expect("cannot locate executable");
    let exe_dir = exe.parent().expect("executable has no parent");

    // Inside a .app bundle: MacOS/../Resources/assets
    let bundle_assets = exe_dir.join("../Resources/assets");
    if bundle_assets.exists() {
        return bundle_assets.canonicalize().unwrap_or(bundle_assets);
    }

    // Development / non-bundle: sibling assets/
    exe_dir.join("assets")
}
```

**Code signing:**
Required for distribution outside the App Store or direct notarized downloads.
Unsigned apps are quarantined by Gatekeeper. You need an Apple Developer account
and a Developer ID certificate.

```sh
codesign --deep --force --sign "Developer ID Application: Your Name (TEAMID)" MyGame.app
xcrun notarytool submit MyGame.app.zip --apple-id ... --team-id ... --wait
xcrun stapler staple MyGame.app
```

---

## Config, Save, and Log Paths

Do not put user data next to the executable. Use platform-appropriate
directories via the `dirs` crate.

```toml
[dependencies]
dirs = "5"
```

```rust
// Config (settings, key bindings)
let config_dir = dirs::config_dir().unwrap().join("my-game");

// Save files
let data_dir = dirs::data_dir().unwrap().join("my-game");

// Logs
let log_dir = dirs::data_local_dir().unwrap().join("my-game").join("logs");
```

Create these directories on first run if they do not exist.

---

## CI Release Workflow

1. Build on each target platform (Linux, Windows, macOS).
2. Strip symbols from the release binary.
3. Copy binary + `assets/` into the package directory layout above.
4. Create a `.zip` (Windows/macOS) or `.tar.gz` (Linux) archive.
5. Upload to GitHub Releases.

Minimal GitHub Actions matrix:
```yaml
strategy:
  matrix:
    include:
      - os: ubuntu-latest
        target: x86_64-unknown-linux-gnu
      - os: windows-latest
        target: x86_64-pc-windows-msvc
      - os: macos-latest
        target: x86_64-apple-darwin
```

---

## Rules

- Never hardcode absolute paths anywhere in the codebase.
- Always bundle `assets/` alongside the executable in the same directory.
- The packaged build must not require any `feature = "dev-tools"` or
  `feature = "profiling"` flags to function correctly.
- Test the packaged build by running the extracted archive, not via `cargo run`,
  before shipping. `cargo run` masks path bugs that only appear in distribution.
