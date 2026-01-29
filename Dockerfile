FROM python:3.9-slim

WORKDIR /app

# This line forces Python to print logs instantly
ENV PYTHONUNBUFFERED=1

# Install dependencies
# We need apt-get to install gosu, then we clean up to keep the image small.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gosu \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Add build argument for version to invalidate cache when version changes
ARG APP_VERSION=unknown
ENV APP_VERSION=${APP_VERSION}

# Copy application code
COPY . .

# Create the config directory
RUN mkdir -p /config

# Expose the port
EXPOSE 5000

# Create the user 'appuser' (UID 1000 initially)
# We do NOT switch to it yet (USER appuser) because entrypoint.sh needs Root 
# to run 'chown' and 'usermod' before the app starts.
RUN useradd -m -u 1000 appuser

# Copy the entrypoint script and make it executable
COPY entrypoint.sh /entrypoint.sh
RUN sed -i 's/\r$//' /entrypoint.sh && \
    chmod +x /entrypoint.sh

# Set the Entrypoint
ENTRYPOINT ["/entrypoint.sh"]

# The CMD remains the same, but now it is passed TO the entrypoint script
CMD ["gunicorn", "-w", "1", "--threads", "4", "-b", "0.0.0.0:5000", "app:app"]