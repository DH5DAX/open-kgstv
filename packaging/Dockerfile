# Same target-platform PyInstaller approach as HamRig Gateway, glibc 2.36 baseline.
FROM python:3.13-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
    tk8.6 libportaudio2 binutils xvfb xauth fonts-dejavu-core libhamlib-utils \
    && rm -rf /var/lib/apt/lists/*
COPY packaging/requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements.txt
WORKDIR /src
