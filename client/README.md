# Personal Secretary — Flutter client

Android and Linux desktop client for Personal Secretary OS.

## Setup

```bash
cd client
flutter pub get
```

## Quality checks

```bash
flutter analyze
flutter test
```

## Run (Linux desktop)

```bash
flutter run -d linux
```

Linux desktop **build** needs the Flutter Linux toolchain and development packages:

- `clang++`, `cmake`, `ninja`, `pkg-config`
- GTK 3 development libraries
- `libsecret-1` development files (`libsecret-devel` / `libsecret-1-dev`) for the existing `flutter_secure_storage_linux` plugin
- GStreamer development files because playback uses `audioplayers` / `audioplayers_linux`:
  - `gstreamer-1.0` development package
  - `gstreamer-plugins-base-1.0` development package

On openSUSE / Fedora-style hosts:

```bash
sudo zypper install gstreamer-devel gstreamer-plugins-base-devel libsecret-devel gtk3-devel
```

On Debian / Ubuntu-style hosts:

```bash
sudo apt-get install libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev libsecret-1-dev libgtk-3-dev
```

Those **devel** packages are required to compile. They are not required to launch an already-built bundle.

Linux desktop **runtime** (running `build/linux/x64/debug/bundle/personal_secretary`) needs the matching shared libraries, not `-devel` headers:

- GTK 3 (`libgtk-3.so.0`)
- `libsecret-1.so.0`
- GStreamer runtime (`libgstreamer-1.0.so.0`, `libgstapp-1.0.so.0`, `libgstbase-1.0.so.0`) from `gstreamer` / `gstreamer-plugins-base` / `libgstapp-1_0-0`

The bundle executable has `RUNPATH=$ORIGIN/lib`. Bundled plugin `.so` files are rewritten at install time to `RUNPATH=$ORIGIN` so sibling libraries such as `libduckdb.so` and `libflutter_linux_gtk.so` resolve without `LD_LIBRARY_PATH`. Do not run `intermediates_do_not_run/personal_secretary`.

Microphone **runtime** tools are separate from playback **build** dependencies. Recording still uses PulseAudio helpers (`parecord`, `pactl`) and optional `ffmpeg` for non-WAV fallback; those are not required to compile the Linux client.

Verify a Linux debug build, then launch the bundle **on the same host**, without extra `LD_LIBRARY_PATH`:

```bash
flutter build linux --debug
./build/linux/x64/debug/bundle/personal_secretary
```

### Linux voice recording runtime

Assistant voice input on Linux uses the `record` package (6.x). The recorder prefers WAV 16 kHz mono when supported; otherwise it falls back to AAC (`m4a`) or Opus (`ogg`) with matching upload MIME types.

`record_linux` 1.x uses PulseAudio tools (not the deprecated `fmedia` binary):

- `parecord` — microphone capture (from `pulseaudio-utils`)
- `pactl` — device queries
- `ffmpeg` — encoding for non-WAV formats (AAC/Opus fallback)

On openSUSE / Fedora-style hosts:

```bash
sudo zypper install pulseaudio-utils ffmpeg
```

WAV recording needs only `parecord`; install `ffmpeg` if AAC/Opus fallback is required.

If runtime tools are missing, voice input shows a recoverable categorized error instead of crashing.

## Run (Android)

```bash
flutter run -d android
```

Debug APK build verified with:

```bash
flutter build apk --debug
```

Android voice input requires `RECORD_AUDIO` (declared in the app manifest). The `record` package handles runtime microphone permission where supported.

## Configuration

Optional default API base URL via dart-define:

```bash
flutter run -d linux --dart-define=SECRETARY_API_BASE_URL=https://your-server.example
```

The server URL is not secret. You can also enter or change it in the app setup screen. It is stored in ordinary app preferences.

## Authentication

PHASE 19.5 uses opaque bearer tokens. There is no username/password login.

1. Enter the Secretary server URL.
2. Paste a bearer token issued by the operator CLI:

   ```bash
   cd backend && python -m app.cli.auth_token issue --label operator
   ```

3. The client calls `GET /me` and only enters the app when authentication succeeds.

The bearer token is stored in platform secure storage (not SharedPreferences). Use **Forget token / disconnect this client** in Account to remove the local credential without deleting Secretary data.

Never put a real bearer token in documentation, logs, or commits.

## Manual Capture

Use the prominent **Capture** action from the app shell. Typed task text is sent to `POST /capture/task` without client-side OpenAI. Optional title, context object IDs, and dependency IDs are supported in the API contract for later UI wiring.

## Voice

Assistant voice input records a short command to a temporary file, uploads it to `POST /assistant/transcribe`, then sends the transcript through the existing Assistant message flow (`POST /assistant/message`) with the current object or notification context preserved.

Voice-origin Assistant answers are spoken through `POST /assistant/speech` and played with `audioplayers` (Android + Linux, Android minSdk 23). Typed answers are not auto-spoken. Synthesized audio is a temp file only and is deleted after playback, stop, error, or dispose.

Voice recordings are ephemeral temp files only. Capture-screen voice is not implemented yet.
