# syntax=docker/dockerfile:1
#
# Cohort Studio API.
#
# Base image conventions (read from the image config of
# gdssingapore/airbase:python-3.13, which this registry path mirrors):
#   - Debian trixie with Python 3.13 in /usr/local, pip available, no uv
#   - WORKDIR /app, and a non-root user "app" (uid 999) whose home is /app
#   - no USER set, so it runs as root unless told otherwise; curl is installed
FROM registry.sgts.gitlab-dedicated.com/innersource/sgts/runtime/airbase/images/gdssingapore/airbase:python-3.13

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

WORKDIR /app

# Dependencies first, so code changes reuse this layer. Every package is
# pinned with its hashes (exported from uv.lock).
COPY requirements.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

COPY --chown=app:app app ./app
COPY --chown=app:app config ./config
COPY --chown=app:app db ./db

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

# HOST and PORT come from the environment (see app/core/config.py).
CMD ["python", "-m", "app"]
