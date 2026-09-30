FROM python:3.12-slim

# gcc/g++ for any sdist builds (torch ships manylinux wheels; this is belt & braces)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# install deps first for layer caching
COPY pyproject.toml ./
RUN pip install --no-cache-dir requests PyMuPDF openpyxl pydantic "laya>=0.3.20"

# then the app
COPY layajobs ./layajobs
COPY config ./config

# data lives on a volume (jobs.db + telegram token persist across rebuilds)
ENV LAYAJOBS_DATA=/data
VOLUME ["/data"]

# run the always-on bot (includes the embedded 06:00 daily refresh)
CMD ["python", "-m", "layajobs", "bot"]
