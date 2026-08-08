# PythonClaw — personal AI agent in pure Python
#
# Quick start:
#   docker build -t pythonclaw .
#   docker run -p 7788:7788 \
#     -e LLM_PROVIDER=deepseek -e DEEPSEEK_API_KEY=sk-... \
#     -v pythonclaw-data:/root/.pythonclaw \
#     pythonclaw
#
# 100% local with Ollama on the host:
#   docker run -p 7788:7788 \
#     -e LLM_PROVIDER=ollama -e OLLAMA_BASE_URL=http://host.docker.internal:11434/v1 \
#     -v pythonclaw-data:/root/.pythonclaw \
#     pythonclaw

FROM python:3.11-slim

# bash is needed by skill setup-check scripts; git helps skills that clone
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash git curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .

# All runtime state (config, memory, skills, sessions) lives here
VOLUME /root/.pythonclaw
EXPOSE 7788

# Inside a container the dashboard must bind all interfaces so the
# published port works; the container boundary is the isolation layer.
ENV PYTHONCLAW_WEB_HOST=0.0.0.0
ENV PYTHONUNBUFFERED=1

CMD ["pythonclaw", "start", "--foreground"]
