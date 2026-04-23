# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install build deps only if you need lxml; default uses html.parser (pure Python)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy metadata first for better layer caching
COPY pyproject.toml README.md LICENSE ./
COPY sovereign_lead_engine.py ./

RUN pip install --upgrade pip && pip install .

# Non-root user
RUN useradd --create-home --shell /bin/bash app \
    && mkdir -p /data && chown -R app:app /data /app
USER app

# Persist DB and exports outside the container
VOLUME ["/data"]
ENV LEAD_DB=/data/leads.db

WORKDIR /data

ENTRYPOINT ["sovereign-lead-engine"]
CMD ["--help"]
