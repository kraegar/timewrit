# Use a slim Python image for the build stage
FROM python:3.10-slim as builder

# Prevents Python from writing .pyc files and ensures output is sent to logs
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

WORKDIR /app

# Install system dependencies for building Python packages (e.g., psycopg2, pillow)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies into a temporary directory
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt
# Ensure gunicorn is installed for production
RUN pip install --no-cache-dir --prefix=/install gunicorn

# --- Final Production Image ---
FROM python:3.10-slim

WORKDIR /app

# Install runtime libraries for Postgres and Image processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libjpeg62-turbo \
    && rm -rf /var/lib/apt/lists/*

# Copy the installed site-packages from the builder stage
COPY --from=builder /install /usr/local

# Copy the rest of the application code
COPY . .

# Expose the Cloud Run default port
ENV PORT 8080
ENV DEBUG False

# Start the application with Gunicorn
# Using 2 workers to keep memory usage low on a shared-core instance
CMD ["gunicorn", "--bind", ":8080", "--workers", "2", "timeline_project.wsgi:application"]
