# HandPack (x265 / MKV)

Single-window GUI for batch transcoding with ffmpeg.

*(Deutsche Version: [README_DE.md](README_DE.md))*

## Installation
    pip install PySide6
Required tools (PATH or common install locations, otherwise a hint is
shown in the window):
- ffmpeg / ffprobe (mandatory)
- dovi_tool (Dolby Vision preservation; falls back to HDR10 if missing)
- mkvmerge / MKVToolNix (preferred DV muxer; falls back to ffmpeg mux)

## Start
    python main.py

## Features
- Drop area (files + folders recursively) and click = file dialog
- Analysis: resolution, codec, bit depth, audio/subtitle streams,
  HDR10/HDR10+/HLG/DV (profile)
- Autocrop over 5 samples, globally toggleable ("Crop analysis" checkbox)
- "Min. crop" option (default 20 px): borders smaller than this per side are
  ignored by the crop analysis, so FullHD/4K stays pixel-perfect (0 = off)
- Compact window header: settings in two rows, small drop area on the right
- Crop can be disabled per row via checkbox, value manually editable
  (w:h:x:y)
- Right-click context menu per row: re-analyze crop, crop preview,
  **quality comparison**, force overwrite, re-queue, per-track audio
  mode/bitrate/channels/DRC, move up/down, remove from list
- **Quality comparison** ("Quality comparison…" in the context menu):
  before committing to a long encode, test a free matrix of resolutions ×
  CRF values × tunes on a configurable number of short samples (1–10,
  default 3) of configurable duration (1–100 s each, default 10 s),
  spread across the runtime. Choose one or more metrics to score each
  variant against the original: **VMAF**, **SSIM**, **PSNR** (all
  computed in a single ffmpeg pass per sample regardless of how many are
  selected — VMAF's `libvmaf` filter computes SSIM/PSNR as side features
  when combined with VMAF, and a `split`-based filtergraph combines
  SSIM+PSNR without VMAF). VMAF requires libvmaf in ffmpeg; falls back to
  SSIM if missing. What the three metrics mean (hover any checkbox in the
  dialog for the same text):
  - **VMAF** (0–100, higher = better) — Netflix's perceptual metric,
    trained on human ratings. Most reliable indicator of how a real
    viewer perceives quality, especially for compression artifacts.
    Recommended default.
  - **SSIM** (0–1, higher = better) — compares local structure/contrast
    instead of raw pixel values. Well-established, but correlates less
    well with human perception than VMAF, especially for blocking/
    ringing artifacts.
  - **PSNR** (dB, higher = better) — simple pixel-wise difference metric.
    Fast, but the weakest correlation with actually perceived quality of
    the three; treat as a rough secondary reference, not the main
    decision-making metric.

  Results table shows score(s), estimated output size,
  and % of the original size; **non-dominated ("Pareto-optimal") rows are
  marked with ★** — a variant is only worth considering if no other
  variant is both smaller *and* at least as good, which is the
  practically correct way to reason about the size/quality trade-off (the
  quality curve is not linear with size, so a simple score-per-MB ratio
  would be misleading). **Double-click any row** (including the reference
  row) to play back its sample/original (QtMultimedia) and visually judge
  quality, not just trust the numbers — sample files are kept until the
  dialog is closed (not deleted right after scoring). **Select multiple
  rows and click "Compare frames"** to view a still frame from each side
  by side at a chosen point in time (default: middle of the sample),
  useful for spotting artifacts a single aggregate score might hide. A
  **"Sample" dropdown** next to the time slider switches all visible cells
  at once between the tested sample points (e.g. 20/50/80% of runtime),
  independent of each cell's own clip dropdown (which picks the variant/
  run instead). **Hovering any image** shows a synchronized magnifier
  (zoomed crop from the full-resolution frame) at the same relative
  position in all cells at once; **right-click → "Open in window"** opens
  the current frame in a separate, freely resizable window.
  Selecting a row and clicking "Apply" sets that row's target/CRF/tune.
  Windows auto-download now fetches the ffmpeg "full" build (needs 7-Zip
  installed, since the full build is only distributed as .7z; falls back
  to the essentials build — same as before, minus VMAF — if 7-Zip isn't
  found). Size estimate is video-only (no audio/subtitles)
- Global target resolution (Original/576p/720p/1080p/2160p), 16:9 rule,
  no upscaling; "Original" keeps the source resolution; overridable per
  row via dropdown in the "Target" column (default follows the global
  setting)
- Global CRF default, overridable per row
- Global preset (ultrafast…veryslow, default medium): speed ↔ quality;
  applied directly for libx265, mapped accordingly for HW encoders
- Global + per-row tune ("Tune" column): Standard / Film Grain (native
  x265 `grain`) / Animation (anime-typical x265 parameters) / Live Action
  (psy-rd/aq). Fully effective only with libx265; NVENC gets spatial-aq,
  other HW encoders ignore it. HDR and tune x265 parameters are merged
  into a single `-x265-params`; only selectable for libx265, grayed out
  otherwise
- Audio streams selectable per file via dropdown checkboxes; shows source
  bitrate and — depending on the audio mode — the target format including
  target bitrate. Audio mode globally switchable: **Copy** / **→ AC3** /
  **→ AAC** (each capped at 5.1, a track already in the matching codec is
  copied unchanged; default target bitrate 192 kb/s at ≤2 channels,
  384 kb/s at 3+ channels).
  Overridable per audio track via right-click context menu ("Audio mode
  (per track)"): mode (Global/Copy/AC3/AAC), target bitrate (96–640 kb/s
  in 10 steps, or "Automatic" per the default), target channels
  (Mono/Stereo/5.1, or "Automatic" = source, capped at 5.1), and Dynamic
  Range Compression (DRC, 0–4 on a HandBrake-style scale, implemented via
  ffmpeg's `acompressor` filter — not a 1:1 reproduction of HandBrake's
  algorithm, but the same purpose: quiet dialogue louder, loud passages
  tamed, e.g. for night-time/low-volume listening; a good starting value
  is **2.0–2.5** — noticeable without severely flattening dynamics/
  spaciousness. 1.0–1.5 is subtle, 3.0+ gets aggressive, 4.0 compresses
  almost everything to the same level).
  Setting a channel or DRC override forces a re-encode even if the source
  is already in the target codec. Overridden tracks show `[override]` in
  the dropdown label, active DRC additionally shows `DRC <level>`.
  Atmos/DTS:X object layers are lost when transcoding — the row is then
  flagged with a warning in the status
- Subtitles and attachments/data streams are always copied unchanged,
  independent of the video mode (Encode or Copy, see below)
- Encoder dropdown: libx265 + automatically detected HW encoders
  (probe-encode at startup), plus a **Copy** entry as the last item —
  selecting it passes the video stream through unchanged (`-c:v copy`,
  no re-encode; DV/HDR pipeline and preset/tune/target are skipped and
  grayed out). Default stays **Software (libx265)**. Overridable per row
  via context menu ("Video mode": Global/Encode/Copy) — handy after a
  quality comparison shows re-encoding isn't worth it for a given file
- HEVC profile (Main/Main 10) and level are not set manually; the
  encoder derives them automatically from the chosen pixel format
  (8-bit vs. 10-bit, see bit depth/HDR detection) resp. from
  resolution/framerate/bitrate
- DV: extract RPU (P7→8.1), HDR10 encode, inject RPU, mux
- Queue grows dynamically: files can be added while encoding is running
- Queue management: checkbox column temporarily excludes files from
  transcoding, context menu "Move up/down" changes the order, "Remove
  from list" deletes the entry — all also work for already queued jobs
  (running jobs are locked)
- Output: source folder + `.<target>.x265.mkv` (parts dot-separated),
  globally overridable, editable per row; existing targets are flagged,
  never overwritten
- Time display at the bottom: job/batch remaining time as well as current
  encoding speed in fps
- Log field ("Log" checkbox, bottom left): shows calls and output of
  ffmpeg, dovi_tool and mkvmerge, plus cropdetect results
- Multilingual (DE/EN), switchable via button bottom left; selection is
  persisted

## Tests
    pip install -r requirements-dev.txt
    pytest
Unit tests for pure logic (crop detection parsing, output-path naming,
ffmpeg command construction, audio mode selection, media-info aggregation,
sysinfo regexes) — no ffmpeg/GUI required, run in well under a second.

## Windows Quick Start
- **setup_and_run.bat** – creates `.venv` once, installs PySide6, starts
  the app (no console window). Requires Python 3.11+ from python.org.
- **build_exe.bat** – builds a standalone `dist\HandPack-<version>.exe`
  with PyInstaller (version from `version.py`), including the app icon
  (`icon.svg` → `icon.ico` via `make_icon.py`). Cleans up the `build/`
  intermediate folder automatically afterwards.

## Persistent Settings
Stored via `QSettings` under organization "Kristian", app "HandPack":
- Windows: `HKCU\Software\Kristian\HandPack`
- Linux: `~/.config/Kristian/HandPack.conf`
- macOS: `~/Library/Preferences/com.Kristian.HandPack.plist`

## Tool Download in the App
If ffmpeg/ffprobe, dovi_tool or mkvmerge are missing, a
**"Download missing tools"** button appears at the bottom. The binaries
are placed in a `.tools/` folder next to the app (or EXE) — no admin
rights needed; the dot prefix keeps sync clients (Nextcloud/OpenCloud)
away from it. An older `tools/` folder is automatically renamed at
startup. Once all tools are present, this becomes
**"Check for tool updates"**: compares the versions of the binaries in
`.tools/` against the download sources and re-downloads outdated ones
after confirmation (tools installed via PATH are left untouched).
Sources: gyan.dev (Windows ffmpeg), johnvansickle.com (Linux),
evermeet.cx (macOS), GitHub releases of quietvoid/dovi_tool,
mkvtoolnix.download (mkvmerge).

mkvmerge auto-download is only available on Windows and only if
**7-Zip** is installed (the portable MKVToolNix archive is BCJ2-packed
7z, which neither Python nor Windows built-in tools can extract).
Without 7-Zip, or on Linux/macOS, install MKVToolNix manually:
<https://mkvtoolnix.download/downloads.html>
(Linux: `apt install mkvtoolnix`, macOS: `brew install mkvtoolnix`).

---

## Docker Deployment (Server)

The app runs headless in the container and is operated via **noVNC in
the browser** (no X server needed on the client, no SSH forwarding).

### Tools Included in the Image
All four tools are already included in the image — no manual download
in the app needed:

| Tool | Source in the image |
|---|---|
| ffmpeg / ffprobe | Static [BtbN](https://github.com/BtbN/FFmpeg-Builds) GPL build (VAAPI + NVENC + libvmaf, needed for the VMAF quality comparison — Debian's own `ffmpeg` package isn't guaranteed to have libvmaf enabled) |
| dovi_tool | fetched from the latest GitHub release at build time |
| mkvmerge | Debian package `mkvtoolnix` |

Opening `http://server-ip:6080/` auto-redirects via a generated
`index.html` to `vnc.html?autoconnect=true&resize=scale` — no manual
URL, no Connect click, automatic scaling. The app window is
automatically maximized on startup (`HANDPACK_MAXIMIZE=1`, see
`docker/supervisord.conf`), filling whatever virtual resolution is set
via `RESOLUTION`.

### Build (local, build only)
    build_docker.bat [namespace]
builds the image locally and tags it with name/version from
`version.py` (e.g. `handpack:0.1` + `handpack:latest`). Optional
namespace:

    build_docker.bat myuser
    → image: myuser/handpack:0.1

### Deploy (push to a registry)
    deploy_docker.bat <registry-host:port> [namespace]
tags the previously locally built image for the target registry and
pushes the version + `latest` tag. Without an argument, the script
prompts for the registry address interactively. **Important: specify
both host AND port** (e.g. `registry.example:5000`) — without a port,
Docker attempts HTTPS on 443 and fails with "connection refused".

Example:
    build_docker.bat myuser
    deploy_docker.bat registry.example:5000 myuser

**Requirement for an HTTP registry without TLS** (default for a
self-hosted local registry): on the build machine, in Docker Desktop →
Settings → Docker Engine, add to the JSON:
```json
{ "insecure-registries": ["registry.example:5000"] }
```
→ Apply & Restart.

### Hosting Your Own Registry (optional)
`docker-compose.registry.yml` – stack that starts a private
Docker registry (`registry:2`) on port 5000. An optional Basic Auth
block is included commented out. Only use on your own LAN (no TLS).

### Start (locally via Compose, with local build)
    docker compose up -d
Then in the browser: **http://server-ip:6080/**

`docker-compose.yml` already ships prepared, partly commented-out
options:
- **`RESOLUTION`** – virtual screen size (e.g. `1920x1080`)
- **`./input` / `./output`** volumes – additional mount examples
  are included as comments
- **`./config:/root/.config/Kristian`** – persists app settings (target
  resolution, CRF, encoder, audio/video mode, language, tool paths, …)
  across container recreation and image updates. Without this volume,
  settings reset to defaults every time the container is rebuilt/updated.
  The container runs as root, so `QSettings` writes to `/root/.config`.
- **File permissions**: since the container runs as root, ffmpeg/dovi_tool/
  mkvmerge write output files owned by root. `umask 000` is set for the
  app process (`docker/supervisord.conf`) so new files/folders come out
  as `666`/`777` (read/write for everyone) instead of the default `644` —
  otherwise a non-root host user accessing `./output` could only read,
  not overwrite/delete, the results. Files written before this change
  need a manual one-time `chmod -R a+rw ./output`.
- **GPU passthrough** (see below)

### Deployment from a registry
`build: .` in the compose file only works if the Docker host has access to
the source code. Easier: build the image + push it to a registry
(`build_docker.bat` + `deploy_docker.bat`, see above) and insert
`docker-compose.dockge.yml` as a stack in your Docker UI (e.g. Portainer, Dockge) — it already uses
`image: <registry>/handpack:<tag>` instead of `build: .`, no source
code needed on the server. Adjust `<REGISTRY>`/`<TAG>` (or the example
values in the file) to your own registry address.

### GPU Passthrough (Unraid)
Prepared commented-out in `docker-compose.yml` for:
- **NVIDIA** – requires `nvidia-container-toolkit` on the Unraid host;
  find the GPU UUID with `nvidia-smi -L`, pin it via `device_ids` (MIG
  instances also supported)
- **AMD / Intel** – passthrough of individual `/dev/dri/renderDXXX`
  nodes; list them with `ls -la /dev/dri/`
- **Intel SR-IOV** – Virtual Functions can be assigned individually
  (VF ≠ physical GPU)

The matching ffmpeg encoder must additionally be selected in the app:
`hevc_nvenc` (NVIDIA), `hevc_amf` (AMD), `hevc_qsv` (Intel/VAAPI).
Kernel drivers themselves always come from the host — a container
cannot bring its own, since the kernel is shared; the image only
provides the matching userspace libraries (VAAPI drivers for AMD/Intel).

Multi-GPU: use `device_ids` (NVIDIA) or specific `renderD1xx` nodes
(AMD/Intel) instead of "all GPUs" to pin a particular card to a
container.
