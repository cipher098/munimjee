# Build only with scripts/v1_runtime_package.py's allowlisted context.
FROM python:3.11-slim-bookworm@sha256:0a310eeecf4e1f5a0743f9a6520c90c88d089c903ca5fd283f501e3a805f5f89
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    V1_STOREFRONT_ASSETS_DIR=/opt/munimjee/storefront-src
COPY requirements.txt runtime.in runtime.lock /app/
RUN python -m pip install --no-cache-dir --only-binary=:all: --require-hashes -r runtime.lock \
    && python -m pip check
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
