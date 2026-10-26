# HandPack – GUI on server via noVNC (browser on port 6080)
# Base: debian:testing-slim (glibc required by PySide6/Qt) – newer package
# versions (ffmpeg, Qt libs, VAAPI drivers) than bookworm-slim. Note: the
# "testing" tag always points to Debian's current testing suite, so it
# silently advances to the next codename over time (currently trixie) —
# less reproducible than pinning e.g. debian:trixie-slim, but stays current
# without Dockerfile changes.
FROM debian:testing-slim

# --- System packages ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Python
    python3 python3-pip python3-venv \
    # Qt runtime dependencies
    libgl1 libegl1 libopengl0 libglib2.0-0 libdbus-1-3 \
    libfontconfig1 libfreetype6 libx11-6 libxext6 libxrender1 \
    libxcb1 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
    libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 \
    libxcb-xkb1 libxkbcommon0 libxkbcommon-x11-0 \
    libxcb-cursor0 \
    # QtMultimedia (sample/original preview playback, quality-comparison
    # dialog) links against PulseAudio's client lib even when nothing plays
    # audio in practice — without it, importing QtMultimedia itself raises
    # ImportError and crashes the whole dialog on open.
    libpulse0 \
    # ffmpeg itself comes from a static BtbN build below (Debian's package
    # is not guaranteed to have libvmaf enabled, needed for the VMAF
    # quality comparison – see the RUN step further down). xz-utils is
    # needed to unpack that build's .tar.xz.
    xz-utils \
    # VAAPI userspace: shared by AMD (radeonsi) and Intel (i965/iHD)
    # driver selection happens via LIBVA_DRIVER_NAME (see docker-compose.yml)
    libva2 libva-drm2 \
    mesa-va-drivers \
    intel-media-va-driver \
    i965-va-driver \
    vainfo \
    # NVIDIA: no package needed here – the NVIDIA Container Toolkit on the
    # host injects libnvidia-encode/libcuda etc. into the container at
    # startup when `--gpus`/`deploy.resources.reservations.devices` is used
    # mkvmerge (MKVToolNix) – preferred DV muxer (Debian ships it in main)
    mkvtoolnix \
    # curl, needed once below to fetch dovi_tool from GitHub releases
    curl ca-certificates \
    # rsvg-convert: renders icon.svg -> favicon.png for the noVNC browser tab
    librsvg2-bin \
    # Virtual framebuffer + VNC
    xvfb x11vnc \
    # Lightweight window manager – Xvfb alone provides no decorations, so
    # windows (dialogs, the frame-compare/preview popups) would be
    # chromeless (no titlebar, no move/close via drag) without it.
    fluxbox \
    # noVNC
    novnc websockify \
    # Process supervisor
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# dovi_tool – not packaged for Debian, fetch the latest Linux release binary.
# GitHub's API requires a User-Agent header (otherwise it 403s / rate-limits
# with no assets, which previously produced an empty DOVI_URL -> curl exit 3).
RUN set -eu; \
    DOVI_URL=$(curl -fsSL -H "User-Agent: HandPack-Build" \
        https://api.github.com/repos/quietvoid/dovi_tool/releases/latest \
        | grep -o 'https://[^"]*x86_64-unknown-linux-musl\.tar\.gz' | head -n1); \
    if [ -z "$DOVI_URL" ]; then \
        echo "ERROR: could not resolve dovi_tool download URL (GitHub API rate limit?)"; \
        exit 1; \
    fi; \
    echo "Fetching dovi_tool: $DOVI_URL"; \
    mkdir -p /tmp/dovi_extract \
    && curl -fsSL "$DOVI_URL" -o /tmp/dovi_tool.tar.gz \
    && tar -xzf /tmp/dovi_tool.tar.gz -C /tmp/dovi_extract \
    && find /tmp/dovi_extract -type f -name 'dovi_tool*' -exec cp {} /usr/local/bin/dovi_tool \; \
    && chmod +x /usr/local/bin/dovi_tool \
    && /usr/local/bin/dovi_tool --version \
    && rm -rf /tmp/dovi_tool.tar.gz /tmp/dovi_extract

# ffmpeg/ffprobe – static BtbN GPL build (VAAPI/NVENC/libvmaf all enabled;
# GPU access itself still comes from the host driver + userspace libs
# above, containers cannot ship kernel drivers). BtbN keeps a "latest" tag
# with a stable asset name, so no GitHub API call (and its rate limit)
# is needed here, unlike the dovi_tool fetch above. The libvmaf filter
# check fails the build early if a future BtbN build ever drops it.
RUN set -eu; \
    FFMPEG_URL="https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz"; \
    curl -fsSL "$FFMPEG_URL" -o /tmp/ffmpeg.tar.xz \
    && mkdir -p /tmp/ffmpeg_extract \
    && tar -xJf /tmp/ffmpeg.tar.xz -C /tmp/ffmpeg_extract \
    && find /tmp/ffmpeg_extract -type f -name ffmpeg -exec cp {} /usr/local/bin/ffmpeg \; \
    && find /tmp/ffmpeg_extract -type f -name ffprobe -exec cp {} /usr/local/bin/ffprobe \; \
    && chmod +x /usr/local/bin/ffmpeg /usr/local/bin/ffprobe \
    && /usr/local/bin/ffmpeg -version \
    && /usr/local/bin/ffmpeg -hide_banner -filters | grep -q libvmaf \
    && rm -rf /tmp/ffmpeg.tar.xz /tmp/ffmpeg_extract

# --- App ---
WORKDIR /app
COPY requirements.txt .
RUN python3 -m pip install --no-cache-dir --break-system-packages -r requirements.txt

COPY . .

# --- Supervisor config ---
COPY docker/supervisord.conf /etc/supervisor/conf.d/handpack.conf

# Browser tab: proper title + favicon instead of the container hostname
# and noVNC's generic icon. favicon.png is rendered from the same icon.svg
# used for the desktop app / EXE, so both stay visually consistent.
RUN rsvg-convert -w 32 -h 32 /app/icon.svg -o /usr/share/novnc/favicon.png \
    && sed -i 's#<title>.*</title>#<title>HandPack</title>#' /usr/share/novnc/vnc.html \
    # vnc.html ships its own <link rel="icon"/"apple-touch-icon"> tags
    # (novnc-icon-sm/lg.png, several sizes) further down in <head> — those
    # win over a tag merely inserted after <head>, since a later same-rel
    # link overrides an earlier one. Remove all of noVNC's own icon links
    # first so ours is the only one left.
    && sed -i '/<link rel="\(icon\|apple-touch-icon\)"/d' /usr/share/novnc/vnc.html \
    && sed -i '/<head>/a\    <link rel="icon" type="image/png" href="favicon.png">' \
        /usr/share/novnc/vnc.html

# noVNC's Debian package ships no index.html at the web root, so opening
# "http://host:6080/" shows a directory listing instead of the viewer.
# Redirect to vnc.html with autoconnect + auto-scaling enabled.
RUN echo '<!DOCTYPE html><html><head>\
<title>HandPack</title>\
<link rel="icon" type="image/png" href="favicon.png">\
<meta http-equiv="refresh" content="0; url=vnc.html?autoconnect=true&resize=scale&title=HandPack">\
</head><body>Redirecting to <a href="vnc.html?autoconnect=true&resize=scale&title=HandPack">noVNC</a>…</body></html>' \
    > /usr/share/novnc/index.html

# Input/output folders mountable from outside
VOLUME ["/input", "/output"]

EXPOSE 6080

CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/conf.d/handpack.conf"]
