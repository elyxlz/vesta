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

# claude_agent_sdk ships its own bundled Claude Code CLI and resolves it at runtime, so the
# image installs no separate `claude` binary. cc_sdk stays in the tree (tmux is kept) but is
# dormant; if ever reactivated it fetches its own pinned binary under ~/.cache/cc-sdk.
RUN mkdir -p /root/.claude
WORKDIR /root

RUN rm -f /usr/bin/pkill /usr/bin/killall

ENV HOME=/root
RUN : > /root/.bashrc
