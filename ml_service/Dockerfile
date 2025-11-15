FROM tiangolo/uvicorn-gunicorn-fastapi:python3.10

# Set metadata for the image
LABEL project="BrainyPedia" \
      maintainer="Tek Raj Chhetri <tekraj@mit.edu>" \
      version="1.0" \
      description="A large scale computational neuroscience knowledge graphs project, fastapi docker image"

# Create app directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
# Install structsense with legacy resolver if needed
RUN pip install --use-deprecated=legacy-resolver "structsense==0.0.4" || \
    pip install --use-deprecated=legacy-resolver --no-deps "structsense==0.0.4"
# Install remaining requirements
RUN pip install -r requirements.txt

# Copy the rest of the application
COPY . .

# Ensure the core directory exists and has correct permissions
RUN mkdir -p /app/core && \
    chmod -R 755 /app/core

# Expose the port the app runs on (internal port - no root privileges needed)
EXPOSE 8007

# Set WEB_CONCURRENCY to match number of workers for pool sizing
ENV WEB_CONCURRENCY=4

# Command to run the application with optimized settings
CMD [ "gunicorn", "core.main:app", \
      "--bind", "0.0.0.0:8007", \
      "--workers", "4", \
      "--worker-class", "uvicorn.workers.UvicornWorker", \
      "--threads", "4", \
      "--max-requests", "1000", \
      "--max-requests-jitter", "50", \
      "--timeout", "220", \
      "--keep-alive", "220", \
      "--log-level", "debug" ]
