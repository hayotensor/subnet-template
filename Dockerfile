# Multi-stage build for smaller image size
FROM python:3.11-slim as builder

# Set working directory
WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    g++ \
    make \
    curl \
    pkg-config \
    git \
    python3-dev \
    libgmp-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml ./
COPY MANIFEST.in ./
COPY README.md ./
COPY subnet ./subnet

# Install the library as an installed package so package discovery and console
# entrypoints match what downstream users get from a wheel/install.
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Production stage
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Create non-root user for security
RUN useradd -m -u 1000 subnetuser && \
    chown -R subnetuser:subnetuser /app

USER subnetuser

# Expose the default blank-node libp2p port. Override CMD/command with
# run_node arguments for node-specific settings.
EXPOSE 38960

ENTRYPOINT ["python", "-m", "subnet.cli.run_node"]
CMD ["--port", "38960"]
