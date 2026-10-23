# The API image: FastAPI and the document pipeline.
#   build:  docker build -t freightlens-api .
FROM python:3.13-slim

# No .pyc files, and print logs at once (so they appear in CloudWatch without delay).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Layer 1: the libraries. Docker re-runs this only when pyproject.toml changes.
# We read the dependency list out of pyproject.toml instead of installing the project itself,
# so this layer stays cached while our own code changes.
COPY pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" > requirements.txt \
    && pip install -r requirements.txt

# Layer 2: our code. It changes on almost every commit, so it comes after the libraries.
# PYTHONPATH tells Python where to find the freight_intel package.
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations
ENV PYTHONPATH=/app/src

# COPY keeps each file's permissions from the machine that built the image. A file that only its owner can read
# (mode 600 on a laptop) would be unreadable for the normal user below, so we make the code readable by everyone.
# Run as a normal user, not root. /app/storage is where uploads go when the local-folder backend is used.
RUN chmod -R a+rX /app/src /app/migrations /app/alembic.ini /app/pyproject.toml \
    && useradd --create-home --uid 10001 app \
    && mkdir -p /app/storage \
    && chown -R app:app /app/storage
USER app

EXPOSE 8000

# "Is the API answering?" Used by Docker now and by ECS later. The slim image has no curl, so Python asks.
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"

# 0.0.0.0 = accept connections from outside the container. 127.0.0.1 would only be reachable from inside it.
CMD ["uvicorn", "freight_intel.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
