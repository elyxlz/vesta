# ── whisper.cpp static libs (CGO deps for the whatsapp skill) ─────────────
# Built at the commit pinned in the skill's go.mod (one owner: build-whisper.sh
# reads the pin from the go.mod sitting next to it). Only the headers and
# static libs are copied into the final image; cmake/g++ and the source tree
# stay in this stage.
FROM debian:trixie-slim AS whisper-build
RUN apt-get update && apt-get install -y --no-install-recommends \
    git ca-certificates gcc g++ cmake make && rm -rf /var/lib/apt/lists/*
COPY agent/skills/whatsapp/cli/go.mod agent/skills/whatsapp/cli/build-whisper.sh /build/
RUN bash /build/build-whisper.sh /opt/whisper.cpp

# Debian 13 (trixie) for git >=2.42. The flat workspace no longer changes sparse-checkout cones,
# but newer git still protects untracked auth/config files if a future migration or manual repair
# operation tries to remove a directory that contains them.
FROM debian:trixie-slim

LABEL org.opencontainers.image.title="Vesta" \
      org.opencontainers.image.description="AI guardian angel that works autonomously on your behalf" \
      org.opencontainers.image.source="https://github.com/elyxlz/vesta" \
      org.opencontainers.image.licenses="MIT"

# The browser skill's OS deps: headless Camoufox is still Gecko and dlopens these at startup, so
# without them every `browser launch` exits 255 before BiDi. The t64 names are trixie's time_t
# rename; gdk-pixbuf comes in via GTK3.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git ca-certificates tzdata gnupg screen tmux \
    libgtk-3-0t64 libx11-xcb1 libdbus-glib-1-2 libxtst6 libasound2t64 && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

# ── browser handover: stream a headed Camoufox to the user so they sign in by hand ──
# The browser skill's primary fallback when a site gates on account trust. handover.py shells out
# to Xvfb -> openbox -> x11vnc -> websockify and symlinks noVNC's assets, so without these a box
# can only report the gap, never escalate. novnc pulls websockify in as a hard dependency. Baked in
# rather than apt-installed on demand: a runtime install dies with the next container rebuild.
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb x11vnc openbox novnc && \
    rm -rf /var/lib/apt/lists/*

# ── Go toolchain + CGO link deps for the whatsapp skill's on-box builds ───
# The whatsapp launcher compiles the CLI from source on every invocation and
# needs go + a C/C++ linker; whisper static libs come from the whisper-build
# stage at the exact paths the launcher's cgo-env.sh expects. Resolve the
# current stable Go at implementation time (curl -fsSL 'https://go.dev/VERSION?m=text')
# and pin it here.
ARG GO_VERSION=1.26.5
RUN apt-get update && apt-get install -y --no-install-recommends gcc g++ libc6-dev ffmpeg && \
    rm -rf /var/lib/apt/lists/* && \
    ARCH=$(dpkg --print-architecture) && \
    curl -fsSL "https://go.dev/dl/go${GO_VERSION}.linux-${ARCH}.tar.gz" | tar -C /usr/local -xz
ENV PATH="/usr/local/go/bin:${PATH}"
COPY --from=whisper-build /opt/whisper.cpp/include /opt/whisper.cpp/include
COPY --from=whisper-build /opt/whisper.cpp/ggml/include /opt/whisper.cpp/ggml/include
COPY --from=whisper-build /opt/whisper.cpp/build-static/src /opt/whisper.cpp/build-static/src
COPY --from=whisper-build /opt/whisper.cpp/build-static/ggml/src /opt/whisper.cpp/build-static/ggml/src
COPY --from=whisper-build /opt/whisper.cpp/.pin /opt/whisper.cpp/.pin

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /root

COPY agent/ ./agent/

WORKDIR /root/agent
# Scoped, never ENV: exported, UV_PROJECT_ENVIRONMENT retargets every uv project, so a skill's
# `uv run` would re-sync the engine venv. PATH exposes the venv instead.
RUN UV_PROJECT_ENVIRONMENT=/root/agent/.venv uv sync --frozen --no-install-project --project core
ENV PATH="/root/agent/.venv/bin:${PATH}"

# Install Claude Code on PATH. claude_agent_sdk would otherwise fall back to its own bundled CLI
# (deep in site-packages), but skills shell out to `claude` directly (e.g. video-use), so it must
# be resolvable on PATH; the SDK then reuses this same binary. cc_sdk stays in the tree (tmux is
# kept) but is dormant; if ever reactivated it fetches its own pinned binary under ~/.cache/cc-sdk.
RUN curl -fsSL https://claude.ai/install.sh | bash && \
    claude --version && \
    mkdir -p /root/.claude
WORKDIR /root

RUN rm -f /usr/bin/pkill /usr/bin/killall

ENV HOME=/root
RUN : > /root/.bashrc
