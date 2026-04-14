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

# Dependencies (cached unless lockfile changes)
COPY agent/pyproject.toml agent/uv.lock ./agent/
WORKDIR /root/vesta/agent
RUN uv sync --frozen --no-install-project

# Source (changes often, but deps are cached above)
COPY agent/src ./src
COPY agent/prompts ./prompts
RUN uv sync --frozen
WORKDIR /root/vesta

# Everything else
COPY agent/ ./agent/

# Remove non-default skills (keep only those listed in default-skills.txt)
RUN for d in agent/skills/*/; do \
      name="$(basename "$d")"; \
      grep -qx "$name" agent/skills/default-skills.txt || rm -rf "$d"; \
    done && rm -f agent/skills/default-skills.txt

# SDK discovers skills from .claude/skills/ relative to cwd
RUN mkdir -p .claude && ln -s ../agent/skills .claude/skills

# Git repo: sparse checkout (agent/ only), HEAD at release tag.
# At first boot the agent creates its named branch from here.
RUN git clone --bare https://github.com/elyxlz/vesta.git .git && \
    git config core.bare false && \
    git sparse-checkout set agent && \
    VERSION=$(grep '^version' agent/pyproject.toml | sed 's/.*"\(.*\)"/\1/') && \
    git reset "v${VERSION}"

RUN rm -f /usr/bin/pkill /usr/bin/killall

ENV HOME=/root
RUN : > /root/.bashrc
