# Stage 1: Builder stage
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --user --no-warn-script-location -r requirements.txt

# Stage 2: Final stage
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libpq5 \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN addgroup --system --gid 1001 django \
    && adduser --system --uid 1001 --gid 1001 --home /home/django django

# Copy Python packages
COPY --from=builder /root/.local /home/django/.local
ENV PATH=/home/django/.local/bin:$PATH

# Copy project
COPY --chown=django:django . .

# Collect static files (build-only secret; real settings come from the environment at runtime)
RUN DJANGO_SECRET_KEY=collectstatic-only DJANGO_ENV=production ALLOWED_HOSTS=localhost \
    python manage.py collectstatic --noinput \
    && chmod +x docker/safarichap/scripts/entrypoint.sh \
    && chown -R django:django /app /home/django/.local

USER django

EXPOSE 8000

ENTRYPOINT ["docker/safarichap/scripts/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--threads", "2", \
     "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-"]
