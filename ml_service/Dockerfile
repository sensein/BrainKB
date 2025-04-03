FROM tiangolo/uvicorn-gunicorn-fastapi:python3.9

# Set metadata for the image
LABEL project="BrainyPedia" \
      maintainer="Tek Raj Chhetri <tekraj@mit.edu>" \
      version="1.0" \
      description="A large scale computational neuroscience knowledge graphs project, fastapi docker image"


COPY . .

RUN pip install -r requirements.txt

# Expose the port the app runs on
EXPOSE 8007

# Command to run the application
# Using workers and threads for handling concurrent requests (over 100)
# workers = (2 * num_cores) + 1, using 4 as a reasonable default
# threads = 8 per worker for I/O-bound operations
CMD [ "gunicorn", "core.main:app", "--bind", "0.0.0.0:8007", "--workers", "9", "--worker-class", "uvicorn.workers.UvicornWorker", "--threads", "8", "--max-requests", "1000", "--max-requests-jitter", "50", "--timeout", "220", "--keep-alive", "220" ]
