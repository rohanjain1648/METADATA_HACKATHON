FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files first (layer caching)
COPY pyproject.toml requirements.txt ./

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the source
COPY . .

# Install the package itself
RUN pip install --no-cache-dir -e .

# Force HTTP transport when running in Docker/Railway
ENV MCP_TRANSPORT=http

# Expose default port (Railway overrides this with $PORT at runtime)
EXPOSE 8000

# Start the MCP server
CMD ["python", "-m", "dataguardian.server"]
