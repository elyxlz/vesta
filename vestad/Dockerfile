# Debian 13 (trixie) for git >=2.42. On git 2.39 (bookworm) `git sparse-checkout set` deletes an
# out-of-cone directory that holds untracked files, taking the agent's untracked
# ~/.claude/.credentials.json with it and de-authing the agent on a skills-install. git >=2.42
# refuses to delete a directory containing untracked files, closing that hole at the root.
FROM debian:trixie-slim

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

# Prune optional skills out of the image: keep only the defaults listed in the
# version-pinned core list (agent/core/default-skills.txt). That list ships inside
# core so the runtime reconciler reads it from the read-only core mount.
RUN for d in agent/skills/*/; do \
      name="$(basename "$d")"; \
      grep -qx "$name" agent/core/default-skills.txt || rm -rf "$d"; \
    done

ENV UV_PROJECT_ENVIRONMENT=/root/agent/.venv
WORKDIR /root/agent
RUN uv sync --frozen --no-install-project --project core

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
