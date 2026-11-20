---
name: gamedev-audio
description: >
  Use when adding or modifying audio playback, sound mixing, music systems,
  or real-time audio synthesis in a Rust game. Trigger when user mentions
  rodio, cpal, sound effects, music playback, audio mixer, or procedural audio.
---

# Rust Game Audio

## Library choice

| Need | Library |
|---|---|
| Simple SFX + music playback | `rodio` |
| Real-time synthesis, custom mixing, tight stream control | `cpal` |

Most 2D games need only `rodio`. Reach for `cpal` when you need beat-synced
music, procedural audio, or control over the sample callback.

## Architecture

Game logic must not call `rodio`/`cpal` directly throughout gameplay code.
Use a command pattern: define an enum, send commands over a channel to a
dedicated audio thread. The audio thread owns all playback state.

```rust
pub enum AudioCommand {
    Play { id: SoundId, volume: f32, looping: bool },
    Stop(SoundId),
    SetVolume(SoundId, f32),
    Pause(SoundId),
    Resume(SoundId),
}

pub struct AudioHandle {
    sender: Sender<AudioCommand>,
}

impl AudioHandle {
    pub fn play(&self, id: SoundId, volume: f32, looping: bool) {
        let _ = self.sender.send(AudioCommand::Play { id, volume, looping });
    }
    pub fn stop(&self, id: SoundId) {
        let _ = self.sender.send(AudioCommand::Stop(id));
    }
}
```

The audio manager thread receives commands, updates `Sink` handles, and
drives the `OutputStream`. Keep all `rodio`/`cpal` types off the main thread.

## rodio patterns

**Keep `OutputStream` alive.** Drop it and all audio stops silently.
Store it in the audio manager struct alongside the `OutputStreamHandle`.

```rust
struct AudioManager {
    _stream: OutputStream,          // must not drop
    stream_handle: OutputStreamHandle,
    sinks: HashMap<SoundId, Sink>,
    sounds: HashMap<SoundId, Arc<[u8]>>,
}
```

**One-shots:** decode and append to a temporary `Sink`, then detach.

```rust
let sink = Sink::try_new(&handle.stream_handle)?;
let cursor = Cursor::new(Arc::clone(&handle.sounds[&id]));
sink.append(rodio::Decoder::new(cursor)?);
sink.detach();
```

**Looping sounds:** create a `Sink`, wrap the source with `.repeat_infinite()`,
keep the `Sink` in the map so you can stop or adjust volume later.

**Pre-load SFX at startup.** Read files into `Arc<[u8]>` once; wrap with
`Cursor` each time you play. Avoids disk I/O on every sound trigger.

```rust
fn load_sound(path: &Path) -> anyhow::Result<Arc<[u8]>> {
    let bytes = std::fs::read(path)?;
    Ok(Arc::from(bytes.into_boxed_slice()))
}
```

## cpal patterns

Use `cpal` when you own the sample loop (synthesizers, procedural effects,
beat-synced mixing).

```rust
let stream = device.build_output_stream(
    &config,
    move |data: &mut [f32], _info: &cpal::OutputCallbackInfo| {
        // REAL-TIME SAFE ONLY - see rules below
        fill_buffer(data, &shared_state);
    },
    |err| eprintln!("audio stream error: {err}"),
    None,
)?;
stream.play()?;
```

**Communicate with the callback** using atomics or a lock-free ring buffer
(`crossbeam-channel` bounded channel works well for parameter updates).
Write parameter changes from the game thread; read them in the callback.

```rust
// Game thread writes:
volume.store((v * 1000.0) as u32, Ordering::Relaxed);

// Audio callback reads:
let v = volume.load(Ordering::Relaxed) as f32 / 1000.0;
```

## Rules

- No heap allocation inside the `cpal` audio callback (no `Vec::new`, no
  `Box`, no `String`, no `format!`).
- No `Mutex` lock in the audio callback hot path - use atomics or lock-free
  channels.
- Load audio files on startup or a background I/O thread, never on the audio
  thread or mid-frame.
- `OutputStream` must be stored and kept alive for the lifetime of audio
  playback.
- Gameplay code communicates with audio only through `AudioCommand` channels,
  never by accessing `Sink` or stream handles directly.
