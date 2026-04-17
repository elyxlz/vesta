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
# .gitignore ensures only relevant files are tracked and that mounts do not pollute the repo.
# Build context is the repo root; this Dockerfile lives at vestad/Dockerfile.
COPY agent/ ./agent/

# Set up git repo with sparse checkout limited to default skills.
# Non-default skills are removed from the image and excluded from sparse checkout,
# so upstream merges won't pull them in. The skills-registry install command adds
# skills to sparse checkout on demand, opting them into future upstream merges.
# Remove non-default skills from the image (they'll be installed via sparse checkout on demand)
RUN for d in agent/skills/*/; do \
      name="$(basename "$d")"; \
      grep -qx "$name" agent/skills/default-skills.txt || rm -rf "$d"; \
    done && rm -f agent/skills/default-skills.txt

# Git repo with sparse checkout — only tracks installed skills so upstream merges
# don't pull in uninstalled ones. Must run AFTER skill pruning above.
RUN git init && git remote add origin https://github.com/elyxlz/vesta.git && \
    git sparse-checkout init --no-cone && \
    printf '/agent/\n!/agent/core/\n!/agent/pyproject.toml\n!/agent/uv.lock\n/.gitignore\n' > .git/info/sparse-checkout && \
    git sparse-checkout reapply && \
    printf '/*\n!.gitignore\n!/agent/\n' > .gitignore

# SDK discovers skills from .claude/skills/ relative to cwd (shared with Claude credentials under ~/.claude)
RUN mkdir -p .claude && ln -s ../agent/skills .claude/skills && \
    printf '{"permissions":{"allow":[]}}\n' > .claude/settings.json

WORKDIR /root/agent
RUN uv sync --frozen --no-install-project
WORKDIR /root

RUN rm -f /usr/bin/pkill /usr/bin/killall

ENV HOME=/root
RUN : > /root/.bashrc
