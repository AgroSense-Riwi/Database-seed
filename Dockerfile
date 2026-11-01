FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Runtime dependencies; keep in sync with [project.dependencies] in pyproject.toml.
RUN pip install --no-cache-dir \
    "faker>=40.43.0" \
    "psycopg[binary]>=3.3.6" \
    "shapely>=2.0"

COPY seed /app/seed

# The schema is owned by the API repository (Alembic). Run the API's
# `alembic upgrade head` against this database BEFORE starting this container;
# the seed fails fast (SchemaNotReadyError) when the API tables are missing.
CMD ["python", "-m", "seed"]
