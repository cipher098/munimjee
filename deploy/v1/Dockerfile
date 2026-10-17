# Build only with scripts/v1_runtime_package.py's allowlisted context.
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    V1_STOREFRONT_ASSETS_DIR=/opt/munimjee/storefront-src
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --only-binary=:all: -r requirements.txt
COPY backend/app /app/app
COPY backend/alembic /app/alembic
COPY backend/alembic.ini /app/alembic.ini
COPY backend/static /app/static
COPY storefront-src /opt/munimjee/storefront-src
COPY runtime-manifest.json /opt/munimjee/runtime-manifest.json
RUN mkdir /app/uploads && chown 10001:10001 /app/uploads
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
