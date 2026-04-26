FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files first (layer caching)
COPY pyproject.toml requirements.txt ./

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Install the package
RUN pip install --no-cache-dir -e .

# Railway injects $PORT at runtime — default to 8000 for local Docker runs
ENV PORT=8000
ENV MCP_TRANSPORT=http

# Use uvicorn to serve the ASGI app — host 0.0.0.0 is required for Railway routing
CMD uvicorn dataguardian.server:app --host 0.0.0.0 --port $PORT
