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

# Expose the port Railway will assign via $PORT
EXPOSE 8000

# Run the MCP server in streamable-HTTP mode
# FastMCP reads PORT from the environment automatically
CMD ["python", "-m", "dataguardian.server"]
