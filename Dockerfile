FROM node:22-bookworm-slim AS node

FROM python:3.12-slim-bookworm
COPY --from=node /usr/local/bin/node /usr/local/bin/node
ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SHORTLIST_DATA_DIR=/data/projects \
    HF_HOME=/data/models
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libgl1 libglib2.0-0 libgomp1 fonts-liberation fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu 'torch>=2.4' torchvision \
    && pip install --no-cache-dir -r requirements.txt 'waitress>=3.0,<4'
RUN apt-get update \
    && apt-get install -y --no-install-recommends fontconfig fonts-symbola \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s "$(python -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())')" /usr/local/bin/ffmpeg
RUN useradd --create-home --uid 10001 shortlist \
    && mkdir -p /data/projects /data/models \
    && chown -R shortlist:shortlist /data
COPY *.py bike-race-hud-verified.mp4 ./
COPY static/ static/
COPY templates/ templates/
USER shortlist
EXPOSE 5050
CMD ["waitress-serve", "--listen=0.0.0.0:5050", "--max-request-body-size=2147483648", "app:app"]
