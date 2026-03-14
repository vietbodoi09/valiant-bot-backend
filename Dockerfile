FROM python:3.11-slim

WORKDIR /app

# Install system deps needed by lighter-python signer binary
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app (exclude local lighter/ stub to avoid conflict with official SDK)
COPY . .
# Remove local lighter stub if it exists (official SDK installed via pip)
RUN rm -rf /app/lighter/

# Expose port
EXPOSE 8080

# Run
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]