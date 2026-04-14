FROM debian:bookworm-slim

LABEL org.opencontainers.image.title="Vesta" \
      org.opencontainers.image.description="Personal assistant agent that works autonomously on your behalf" \
      org.opencontainers.image.source="https://github.com/elyxlz/vesta" \
      org.opencontainers.image.licenses="MIT"

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git ca-certificates tzdata && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://claude.ai/install.sh | bash

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /root/vesta

# Git repo — agent tracks local changes (skills, prompts, memory) on its branch.
# Core code (src/vesta, pyproject.toml, uv.lock) is mounted by vestad at runtime.
RUN git init && git remote add origin https://github.com/elyxlz/vesta.git && \
    git sparse-checkout init --cone && git sparse-checkout set agent

# Copy agent-owned files from build context (matches local code in dev,
# release code in prod).
COPY agent/MEMORY.md agent/MEMORY.md
COPY agent/prompts/ agent/prompts/
COPY agent/skills/ agent/skills/

# Reduce image size: remove non-default skills
RUN for d in agent/skills/*/; do \
      name="$(basename "$d")"; \
      grep -qx "$name" agent/skills/default-skills.txt || rm -rf "$d"; \
    done && rm -f agent/skills/default-skills.txt

# SDK discovers skills from .claude/skills/ relative to cwd
RUN mkdir -p .claude && ln -s ../agent/skills .claude/skills

# Deps (cached unless lockfile changes). These files are also mounted at
# runtime, but we COPY them here so uv can install dependencies into the
# image layer — the mount overlays these copies at runtime.
COPY agent/pyproject.toml agent/uv.lock ./agent/
WORKDIR /root/vesta/agent
RUN uv sync --frozen --no-install-project
WORKDIR /root/vesta

RUN rm -f /usr/bin/pkill /usr/bin/killall

ENV HOME=/root
RUN : > /root/.bashrc
