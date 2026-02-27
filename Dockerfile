FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git ca-certificates && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /root/vesta

# Dependencies (cached unless lockfile changes)
COPY agent/pyproject.toml agent/uv.lock agent/
RUN cd agent && uv sync --frozen --no-install-project

# Claude binary (from cached deps layer — won't change unless deps change)
RUN ln -s $(find /root/vesta/agent/.venv -name claude -path "*/claude_agent_sdk/_bundled/*" -type f) /usr/local/bin/claude

# Source (changes often, but deps are cached above)
COPY . .
RUN cd agent && uv sync --frozen

# State dirs
WORKDIR /root
RUN mkdir -p /root/memory/skills /root/notifications /root/logs /root/data

ENV HOME=/root
ENV IS_SANDBOX=1
ENTRYPOINT ["uv", "run", "--project", "/root/vesta/agent", "python", "-m", "vesta.main"]
