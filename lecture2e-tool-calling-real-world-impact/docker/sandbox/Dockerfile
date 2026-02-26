FROM python:3.11-slim

# Install basic utilities
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    vim nano curl wget git ca-certificates tini && \
    apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false && \
    rm -rf /var/lib/apt/lists/*

# Create sandbox workspace
WORKDIR /sandbox
RUN chmod 777 /sandbox

# Create a non-root user
RUN useradd -m -u 1000 -s /bin/bash sandbox
USER sandbox
ENV HOME=/home/sandbox

# Keep container running
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sleep", "infinity"]
