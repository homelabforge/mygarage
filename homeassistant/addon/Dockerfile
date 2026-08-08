# MyGarage Supervisor add-on — wraps the published MyGarage image and maps
# Supervisor options into environment variables before starting Granian.
ARG BUILD_FROM=ghcr.io/homelabforge/mygarage:latest
FROM ${BUILD_FROM}

USER root

# bashio helpers for reading /data/options.json on Supervised HA
RUN apt-get update && \
    apt-get install -y --no-install-recommends jq bash curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY rootfs /

RUN chmod +x /run.sh /etc/services.d/mygarage/run || chmod +x /run.sh

# Supervisor expects the entrypoint to stay PID 1; run.sh maps options then
# execs Granian.
ENTRYPOINT ["/run.sh"]
