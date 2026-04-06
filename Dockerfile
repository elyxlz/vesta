FROM debian:bookworm-slim

LABEL org.opencontainers.image.title="Vesta" \
      org.opencontainers.image.description="Personal assistant agent that works autonomously on your behalf" \
      org.opencontainers.image.source="https://github.com/elyxlz/vesta" \
      org.opencontainers.image.licenses="MIT"

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git ca-certificates && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://claude.ai/install.sh | bash

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /root/vesta

# Dependencies (cached unless lockfile changes)
COPY agent/pyproject.toml agent/uv.lock ./
RUN uv sync --frozen --no-install-project

# Source (changes often, but deps are cached above)
COPY agent/src ./src
COPY agent/prompts ./prompts
RUN uv sync --frozen

# Everything else
COPY agent/ .

# Remove non-default skills (keep only those listed in default-skills.txt)
RUN for d in skills/*/; do \
      name="$(basename "$d")"; \
      grep -qx "$name" skills/default-skills.txt || rm -rf "$d"; \
    done && rm -f skills/default-skills.txt

# SDK discovers skills from .claude/skills/ relative to cwd
RUN mkdir -p .claude && ln -s ../skills .claude/skills

# Bare repo for upstream skill (fetch/worktree/show without exposing cli/app as working files)
RUN git clone --bare --single-branch https://github.com/elyxlz/vesta.git .git && \
    git config core.bare false

RUN rm -f /usr/bin/pkill /usr/bin/killall

ENV HOME=/root
