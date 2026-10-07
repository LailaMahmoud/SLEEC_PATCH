# SLEEC-PATCH slim container image (for Cloudflare Containers).
# Serves ONLY the SLEEC-PATCH workbench + resolution-pipeline routes via the
# slim launcher (sleec_patch_local.py) — no  ML stack.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

WORKDIR /app

# Install dependencies first for better layer caching.
# Uses the SLIM requirements (no torch/transformers/spacy) so the image is
# small enough to start on Cloudflare.
COPY requirements.docker.txt ./requirements.docker.txt
RUN pip install --no-cache-dir -r requirements.docker.txt

# Application code.
COPY SLEECpatch/app ./app
COPY sleec ./sleec

# Let Python find both the 'app' package and the 'sleec' module
ENV PYTHONPATH=/app/app:/app

# Scratch files the LEGOS_SLEEC analyzer reads/writes (relative to cwd).
# Created empty; the analyzer overwrites proof.txt on each run.
RUN touch proof.txt simplified.txt && mkdir -p instance

EXPOSE 8080


CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "2", \
     "--timeout", "300", "deployment_app:app"]
