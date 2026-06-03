FROM debian:bookworm-slim

LABEL org.opencontainers.image.title="Vesta" \
      org.opencontainers.image.description="Personal assistant agent that works autonomously on your behalf" \
      org.opencontainers.image.source="https://github.com/elyxlz/vesta" \
      org.opencontainers.image.licenses="MIT"

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git ca-certificates tzdata gnupg screen tmux && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /root

COPY agent/ ./agent/

RUN for d in agent/skills/*/; do \
      name="$(basename "$d")"; \
      grep -qx "$name" agent/skills/default-skills.txt || rm -rf "$d"; \
    done && rm -f agent/skills/default-skills.txt

WORKDIR /root/agent
RUN uv sync --frozen --no-install-project

# Claude Code is pinned and owned by cc_sdk (CLAUDE_VERSION in cc_sdk/_claude_bin.py): it
# downloads+verifies the matching native binary on demand, so the version never depends on
# what's installed on the host or drifts via auto-update. Pre-fetch it into the image here
# (so first-start pays no download) and symlink it onto PATH for any direct `claude` calls.
RUN CLAUDE_BIN="$(uv run python -m cc_sdk._claude_bin)" && \
    ln -sf "$CLAUDE_BIN" /usr/local/bin/claude && \
    claude --version
WORKDIR /root

RUN rm -f /usr/bin/pkill /usr/bin/killall

ENV HOME=/root
RUN : > /root/.bashrc
