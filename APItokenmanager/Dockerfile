# Assuming you already have a Dockerfile setup for Django
FROM python:3.8

# Set the working directory
WORKDIR /app

# Copy project code
COPY . /app

# Install dependencies
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Copy the .env file to the container
COPY .env /app/.env

# Install python-decouple to read environment variables
RUN pip install python-decouple

# Run migrations
RUN python manage.py makemigrations
RUN python manage.py migrate

# Environment variables for creating superuser
ARG DJANGO_SUPERUSER_USERNAME
ARG DJANGO_SUPERUSER_EMAIL
ARG DJANGO_SUPERUSER_PASSWORD

# Read environment variables from .env file
RUN export $(cat .env | xargs) && \
    python manage.py createsuperuser --noinput --username $DJANGO_SUPERUSER_USERNAME --email $DJANGO_SUPERUSER_EMAIL

# Command to run the app
CMD ["gunicorn", "-b", "0.0.0.0:8000", "APIAuthManager.wsgi:application"]
