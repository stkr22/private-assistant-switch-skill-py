FROM python:3.13-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -s /sbin/nologin -M appuser \
    && mkdir -p /app /app/config \
    && chown -R appuser:appuser /app

# Set working directory
WORKDIR /app

# Copy and install the wheel file
ARG WHEEL_FILE=my_wheel.whl
COPY dist/${WHEEL_FILE} /tmp/${WHEEL_FILE}

# Install dependencies and clean up in one layer
RUN pip install --no-cache-dir /tmp/${WHEEL_FILE} \
    && rm -rf /tmp/* \
    && rm -rf /var/cache/apt/* \
    && rm -rf /root/.cache/*

# Switch to non-root user
USER appuser

ENV PRIVATE_ASSISTANT_CONFIG_PATH=template.yaml

ENTRYPOINT ["private-assistant-switch-skill"]
