# Assuming you already have a Dockerfile setup for Django
FROM python:3.8

# Copy project code
COPY . .
WORKDIR .

# Install dependencies
RUN pip install -r requirements.txt

# Run migrations and create superuser
RUN python manage.py makemigrations
RUN python manage.py migrate
RUN DJANGO_SUPERUSER_USERNAME=brainadmin \
DJANGO_SUPERUSER_PASSWORD=brainadmin \
DJANGO_SUPERUSER_EMAIL="brainadmin@admin.com" \
python manage.py createsuperuser --noinput

# Command to run the app
CMD ["gunicorn", "-b", "0.0.0.0:8000", "BrainyPediaApp.wsgi:application"]
