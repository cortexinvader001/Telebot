FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 DEBIAN_FRONTEND=noninteractive

# CLI tools the agent (and the pdf skill) use. Render's native Python runtime can't apt-get these.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg git curl ca-certificates poppler-utils qpdf tesseract-ocr imagemagick jq zip unzip nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# Unprivileged user that every agent shell command runs as (the bot itself stays root so it can
# drop privileges, and so its environment/secrets and database are unreadable to those commands).
RUN groupadd -g 1001 sandbox && useradd -u 1001 -g 1001 -m -s /bin/bash sandbox

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

ENV DATA_DIR=/data SANDBOX_UID=1001 SANDBOX_GID=1001 AUTO_SETUP_TOOLS=0
RUN mkdir -p /data

CMD ["python", "bot.py"]
