FROM python:3.11.9-slim AS python-base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    # https://python-poetry.org/docs#ci-recommendations
    POETRY_VERSION=1.8.3 \
    POETRY_HOME="/opt/poetry" \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    PYSETUP_PATH="/opt/pysetup" \
    VENV_PATH="/opt/pysetup/.venv"

# Prepend poetry and venv to path
ENV PATH="$POETRY_HOME/bin:$VENV_PATH/bin:$PATH"


# Install system dependencies
RUN apt-get update \
    && apt-get install --no-install-suggests --no-install-recommends -y \
        curl \
        build-essential

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 -

# Copy project requirement files
COPY . .

# Install project dependencies - uses $POETRY_VIRTUALENVS_IN_PROJECT internally
RUN poetry install --no-interaction --no-ansi

# Expose port
EXPOSE 8000

# Command to run uvicorn server with hot reloading
CMD ["poetry", "run", "uvicorn", "brain2kg.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]