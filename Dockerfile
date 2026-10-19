FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

RUN pip install --no-cache-dir \
    "alembic>=1.15" \
    "faker>=40.43.0" \
    "geoalchemy2>=0.18" \
    "psycopg[binary]>=3.3.6" \
    "sqlalchemy>=2.0"

COPY api/apps/api/alembic.ini /app/alembic.ini
COPY api/apps/api/migrations /app/migrations
COPY api/apps/api/src /app/src
COPY database/seed /app/seed

CMD ["sh", "-c", "alembic upgrade head && python -m seed"]