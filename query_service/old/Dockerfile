FROM tiangolo/uvicorn-gunicorn-fastapi:python3.9

# Set metadata for the image
LABEL project="BrainyPedia" \
      maintainer="Tek Raj Chhetri <tekraj@mit.edu>" \
      version="1.0" \
      description="A large scale computational neuroscience knowledge graphs project, fastapi docker image"


COPY . .

RUN pip install -r  requirements.txt

# Expose the port the app runs on
EXPOSE 8010

# Command to run the application with increased timeout settings for large file processing
# --timeout-keep-alive: Keep connections alive for 120 seconds (for large file uploads)
# --timeout-graceful-shutdown: Allow 60 seconds for graceful shutdown
# Note: Large files (10MB+) are processed in background tasks to avoid timeouts
CMD [ "uvicorn", "core.main:app", "--host", "0.0.0.0", "--port", "8010", "--timeout-keep-alive", "120", "--timeout-graceful-shutdown", "60"]
