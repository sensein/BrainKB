FROM tiangolo/uvicorn-gunicorn-fastapi:python3.11

# Set metadata for the image
LABEL project="BrainyPedia" \
      maintainer="Tek Raj Chhetri <tekraj@mit.edu>" \
      version="1.0" \
      description="A large scale computational neuroscience knowledge graphs project, fastapi docker image"

# Create app directory
WORKDIR /app

# PDF export of SynthScholar reviews (core/synth_scholar/review_pdf.py): pandoc renders
# the review's Markdown with Typst, so no TeX toolchain is needed. Debian's pandoc
# predates Typst output (3.1.2+), so both come from their pinned releases.
ARG PANDOC_VERSION=3.12.1
ARG TYPST_VERSION=0.15.1
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates xz-utils fonts-dejavu-core \
    && arch="$(dpkg --print-architecture)" \
    && curl -fsSL -o /tmp/pandoc.deb \
       "https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}/pandoc-${PANDOC_VERSION}-1-${arch}.deb" \
    && dpkg -i /tmp/pandoc.deb && rm /tmp/pandoc.deb \
    && case "$arch" in amd64) t=x86_64-unknown-linux-musl ;; arm64) t=aarch64-unknown-linux-musl ;; *) echo "unsupported arch $arch" && exit 1 ;; esac \
    && curl -fsSL "https://github.com/typst/typst/releases/download/v${TYPST_VERSION}/typst-${t}.tar.xz" | tar -xJ -C /tmp \
    && mv "/tmp/typst-${t}/typst" /usr/local/bin/typst && rm -rf "/tmp/typst-${t}" \
    && rm -rf /var/lib/apt/lists/*

# eMudhra/emSign CA incident (October 2026): the emSign root was distrusted, and pip
# below 26.2.2 still trusts it through its own vendored certifi, alongside the system
# store — so pip's TLS to PyPI could be intercepted. Before anything else is
# downloaded, install the fixed pip and certifi from pinned wheels, hash-checked, so
# even a tampered response is refused. Advisory:
# https://discuss.python.org/t/information-for-python-users-regarding-emudhra-emsign-ca-certificate-security-incident/109576
RUN printf '%s\n' \
      'pip==26.2.2 --hash=sha256:fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70' \
      'certifi==2026.10.19 --hash=sha256:42d35340cc5b9ba78e818ddbff0c5b1c2b779de448a340fd1b989f5fa8670e1b' \
      > /tmp/ca-fix.txt \
    && pip install --no-cache-dir --require-hashes -r /tmp/ca-fix.txt \
    && rm /tmp/ca-fix.txt

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
# Install structsense with legacy resolver if needed
RUN pip install --use-deprecated=legacy-resolver "structsense==0.0.4" || \
    pip install --use-deprecated=legacy-resolver --no-deps "structsense==0.0.4"
# Install remaining requirements
RUN pip install -r requirements.txt \
    && python -c "import certifi, pip; from pip._vendor import certifi as vc; \
assert tuple(map(int, pip.__version__.split('.')[:3])) >= (26, 2, 2), pip.__version__; \
assert certifi.__version__ >= '2026.10.19' and vc.__version__ >= '2026.10.19', (certifi.__version__, vc.__version__)"

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
