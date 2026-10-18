# repo_intel — Dockerfile for development and production

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install system build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Copy pyproject.toml and requirements first, then install
COPY pyproject.toml .
COPY requirements.txt .
# Copy src so pip install . can find the package
COPY src/ src/
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install .

COPY tests/ tests/
COPY alembic/ alembic/
COPY alembic.ini .

EXPOSE 8765

CMD ["repo-intel", "serve"]
