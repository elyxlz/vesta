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

# Core skills from registry
COPY agent/skills-registry/reminders ./skills/reminders
COPY agent/skills-registry/tasks ./skills/tasks
COPY agent/skills-registry/upstream ./skills/upstream
COPY agent/skills-registry/dream ./skills/dream
COPY agent/skills-registry/what-day ./skills/what-day
COPY agent/skills-registry/browser ./skills/browser
COPY agent/skills-registry/skills ./skills/skills

ENV HOME=/root
ENV STATE_DIR=/root/vesta
ENV IS_SANDBOX=1
ENTRYPOINT ["uv", "run", "--project", "/root/vesta", "python", "-m", "vesta.main"]
