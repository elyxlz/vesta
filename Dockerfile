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
COPY agent/pyproject.toml agent/uv.lock agent/
RUN cd agent && uv sync --frozen --no-install-project

# Source (changes often, but deps are cached above)
COPY . .
RUN cd agent && uv sync --frozen

# State dirs
WORKDIR /root
RUN mkdir -p /root/vesta/agent/memory/conversations /root/vesta/agent/memory/dreamer /root/notifications /root/logs /root/data

ENV HOME=/root
ENV IS_SANDBOX=1
ENTRYPOINT ["uv", "run", "--project", "/root/vesta/agent", "python", "-m", "vesta.main"]
