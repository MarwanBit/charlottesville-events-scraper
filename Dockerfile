# Events scraper: run with  docker run --env DATABASE_URL=postgresql+psycopg://... your-image
FROM python:3.12-slim

# Headless browser for nodriver (Chromium; required for browser fallback on EC2).
# Xvfb = virtual display for headed Chrome. x11vnc = stream that display so you can view it.
# Extra libs are needed so Chromium can actually start in a slim image.
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    xvfb \
    xauth \
    x11vnc \
    curl \
    # Common Chromium runtime deps for headless / remote-debugging use
    libnss3 \
    libxss1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    libdrm2 \
    libgbm1 \
    libxdamage1 \
    libxrandr2 \
    libxcomposite1 \
    libxfixes3 \
    libxcb1 \
    libx11-6 \
    libpangocairo-1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libxkbcommon0 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user so Chromium/nodriver don't hit root sandbox issues.
RUN useradd -m -u 1000 appuser

# App working directory
WORKDIR /app

# Python deps: psycopg (v3) for postgresql+psycopg://, psycopg2-binary for postgresql://
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt 'psycopg[binary]' 'psycopg2-binary'

# App code (respects .dockerignore)
COPY . .

# Ensure app files are owned by the non-root user
RUN chown -R appuser:appuser /app

USER appuser

ENV PYTHONUNBUFFERED=1
ENV HEADLESS=1
# Default browser binary locations for nodriver/NoDriverClient. Can be overridden at runtime.
ENV CHROME_PATH=/usr/bin/chromium
ENV BROWSER_PATH=/usr/bin/chromium
# Keep container running. Run pipeline manually:
#   docker exec -it <container> python -m src.app
# Non-headless in Docker (uses virtual display; you won't see the window unless you add VNC):
#   docker exec -it -e HEADLESS=0 <container> xvfb-run -a python -m src.app
CMD ["sleep", "infinity"]
