# Calendars & Closures API — deterministic image for Azure Container Apps.
# Used by `az containerapp up --source .` (a Dockerfile here takes precedence
# over Oryx buildpacks, so the build always includes the current source).
FROM python:3.11-slim

WORKDIR /app

# Install dependencies first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application source (app/, etc.). This layer's cache key is the file
# contents, so adding/editing routers invalidates it and ships the new code.
COPY . .

EXPOSE 8000

# Ingress target port is 8000 (see `az containerapp up --target-port 8000`).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
