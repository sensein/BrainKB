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

# Command to run the application
CMD [ "uvicorn", "core.main:app", "--host", "0.0.0.0", "--port", "8006"]
