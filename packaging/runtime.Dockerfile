# Clean runtime smoke test: no Python, Tcl/Tk, PortAudio, pip or build toolchain.
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb xauth fonts-dejavu-core libxft2 libfontconfig1 libxrender1 \
    libasound2 libjack-jackd2-0 libpulse0 libglib2.0-0 libhamlib-utils \
    && rm -rf /var/lib/apt/lists/*
