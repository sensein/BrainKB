FROM tiangolo/uvicorn-gunicorn-fastapi:python3.9

# Set metadata for the image
LABEL project="BrainyPedia" \
      maintainer="Tek Raj Chhetri <tekraj@mit.edu>" \
      version="1.0" \
      description="A large scale computational neuroscience knowledge graphs project, fastapi docker image"


COPY . .

RUN pip install -r requirements.txt

# Expose the port the app runs on
EXPOSE 8006

# Command to run the application with increased file size limits
#CMD [ "uvicorn", "core.main:app", "--host", "0.0.0.0", "--port", "8006", "--limit-concurrency", "1000", "--limit-max-requests", "10000", "--timeout-keep-alive", "800", "--proxy-headers", "--forwarded-allow-ips", "*", "--workers", "4", "--limit-request-line", "0", "--limit-request-field_size", "0", "--limit-request-fields", "0", "--limit-request-body", "1610612736"]
CMD [ "uvicorn", "core.main:app", "--host", "0.0.0.0", "--port", "8006", "--limit-concurrency", "1000", "--limit-max-requests", "10000", "--timeout-keep-alive", "800",   "--workers", "4" ]