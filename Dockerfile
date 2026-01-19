FROM python:3.9-slim

WORKDIR /app

# This line forces Python to print logs instantly (Fixes the empty log issue)
ENV PYTHONUNBUFFERED=1

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create the config directory
RUN mkdir -p /config

# Expose the port
EXPOSE 5000

# Run with Gunicorn
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:5000", "app:app"]