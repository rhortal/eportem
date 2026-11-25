# CheckIn service: web UI, API and scheduler in one process (docs/refactor/PLAN.md).
# No configuration is baked in: everything comes from CHECKIN_* variables (see
# .env.example) or a mounted config file. Data lives in the /data volume.
FROM python:3.13-slim-trixie

# Chromium is only started to log in (reCAPTCHA); Debian's packages match the
# driver to the browser. tini reaps Chromium's child processes.
RUN apt-get update \
 && apt-get install -y --no-install-recommends chromium chromium-driver tini fonts-liberation \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 --user-group checkin \
 && mkdir -p /data && chown checkin:checkin /data

WORKDIR /app
COPY requirements.txt requirements-service.txt ./
RUN pip install --no-cache-dir -r requirements-service.txt

# The service, the fake ePortem (for trying it out), and the legacy modules
# import-legacy reads its constants from.
COPY checkin ./checkin
COPY fake_eportem ./fake_eportem
COPY utility ./utility
COPY skill ./skill

ENV PYTHONUNBUFFERED=1 \
    CHECKIN_DATA_DIR=/data \
    CHECKIN_CHROMIUM_PATH=/usr/bin/chromium \
    CHECKIN_CHROMEDRIVER_PATH=/usr/bin/chromedriver \
    # Chromium's own sandbox can't start as a non-root user here; the container isolates it.
    CHECKIN_BROWSER_SANDBOX=false

USER checkin
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"CHECKIN_PORT\", \"8080\")}/healthz', timeout=4)"
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "checkin", "serve"]
