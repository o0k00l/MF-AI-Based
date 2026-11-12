# Production Dockerfile for Mutual Fund SIP Decision Support API
# Multi-stage build for minimal attack surface

# Build stage
FROM python:3.11-slim-bookworm AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy hash-locked requirements
COPY requirements.lock ./
COPY requirements.txt ./

# Install dependencies with hash verification
RUN python -m pip install --no-cache-dir --require-hashes -r requirements.lock

# Runtime stage
FROM python:3.11-slim-bookworm AS runtime

WORKDIR /app

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY --chown=appuser:appuser api/ ./api/
COPY --chown=appuser:appuser core/ ./core/
COPY --chown=appuser:appuser ingestion/ ./ingestion/
COPY --chown=appuser:appuser services/ ./services/
COPY --chown=appuser:appuser data/ ./data/
COPY --chown=appuser:appuser tests/ ./tests/

# Copy requirements for verification
COPY --chown=appuser:appuser requirements.lock ./
COPY --chown=appuser:appuser requirements.txt ./

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start command - production app requires evidence bundle and auth
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# The production app factory requires MF_SIP_EVIDENCE_BUNDLE_DIR to be set
# and will enforce authentication (require_auth=True)
CMD ["uvicorn", "api.sip_production:create_production_sip_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]