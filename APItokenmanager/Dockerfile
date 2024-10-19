# Assuming you already have a Dockerfile setup for Django
FROM python:3.10

# Set the working directory
WORKDIR /app

# Copy project code
COPY . /app

# Install dependencies
# Install dependencies
RUN pip install --upgrade pip && \
    pip install -r requirements.txt && \
    pip install python-decouple

# Copy the .env file to the container
COPY .env /app/.env


# Environment variables for creating superuser
ARG DJANGO_SUPERUSER_USERNAME
ARG DJANGO_SUPERUSER_EMAIL
ARG DJANGO_SUPERUSER_PASSWORD

# Read environment variables from .env file
RUN python manage.py makemigrations && \
    python manage.py migrate && \
    export $(cat .env | xargs) && \
    python manage.py createsuperuser --noinput --username $DJANGO_SUPERUSER_USERNAME --email $DJANGO_SUPERUSER_EMAIL