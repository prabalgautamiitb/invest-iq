FROM python:3.13-slim
WORKDIR /app
ENV PYTHONPATH=/app/src PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
# Exported from uv.lock; pip verifies the exact locked distribution hashes.
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations
RUN useradd --system --uid 10001 appuser
USER appuser
EXPOSE 8080
CMD ["uvicorn", "investiq.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
