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

WORKDIR /root

# Git repo at $HOME — agent tracks local changes (skills, prompts, memory) on its branch.
# Core code is baked into the image; with manage_agent_code=true, vestad mounts newer copies.
# .gitignore ensures only relevant files are tracked and that mounts do not pollute the repo
COPY agent/ ./agent/

# Set up git repo with sparse checkout limited to default skills.
# Non-default skills are removed from the image and excluded from sparse checkout,
# so upstream merges won't pull them in. The skills-registry install command adds
# skills to sparse checkout on demand, opting them into future upstream merges.
RUN git init && git remote add origin https://github.com/elyxlz/vesta.git && \
    git sparse-checkout init --cone && \
    SKILL_DIRS=$(find agent/skills -mindepth 1 -maxdepth 1 -type d | tr '\n' ' ') && \
    git sparse-checkout set agent/core agent/prompts agent/dreamer $SKILL_DIRS && \
    printf '/*\n!.gitignore\n!/agent/\n' > .gitignore

# Remove non-default skills from the image (they'll be installed via sparse checkout on demand)
RUN for d in agent/skills/*/; do \
      name="$(basename "$d")"; \
      grep -qx "$name" agent/skills/default-skills.txt || rm -rf "$d"; \
    done && rm -f agent/skills/default-skills.txt

# SDK discovers skills from .claude/skills/ relative to cwd (shared with Claude credentials under ~/.claude)
RUN mkdir -p .claude && ln -s ../agent/skills .claude/skills && \
    printf '{"permissions":{"allow":[]}}\n' > .claude/settings.json

WORKDIR /root/agent
RUN uv sync --frozen --no-install-project
WORKDIR /root

RUN rm -f /usr/bin/pkill /usr/bin/killall

ENV HOME=/root
RUN : > /root/.bashrc
