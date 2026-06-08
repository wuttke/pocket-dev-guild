# Multi-stage Dockerfile for Pocket Dev Guild backend
# Includes Node.js, Python, and Auggie CLI

FROM node:22-bookworm-slim AS base

# Install Python and other system dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-venv \
    python3-pip \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Auggie CLI globally via npm
RUN npm install -g @augmentcode/auggie

# Set working directory
WORKDIR /app

# Copy Python requirements first for better caching
COPY requirements.txt .

# Create virtual environment and install Python dependencies
RUN python3 -m venv .venv \
    && .venv/bin/pip install --no-cache-dir --upgrade pip \
    && .venv/bin/pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create config from example if not exists (can be overridden via volume mount)
RUN if [ ! -f config.yaml ]; then cp config.example.yaml config.yaml; fi

# Expose the default FastAPI port
EXPOSE 8000

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/docs || exit 1

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
