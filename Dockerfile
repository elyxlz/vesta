FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git ca-certificates && rm -rf /var/lib/apt/lists/*

# Node.js (bundled claude-agent-sdk needs it)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs && rm -rf /var/lib/apt/lists/*

# uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

COPY . /root/vesta
WORKDIR /root
RUN cd /root/vesta && uv sync --frozen

# State dirs
RUN mkdir -p /root/memory/skills /root/notifications /root/logs /root/data

ENV HOME=/root
ENTRYPOINT ["uv", "run", "--project", "/root/vesta", "vesta"]
