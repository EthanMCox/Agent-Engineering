FROM python:3.11-slim

# Create non-root user and group
ARG UNPRIV_UID=1000
ARG UNPRIV_GID=1000

RUN groupadd -g ${UNPRIV_GID} sandbox && \
    useradd -m -u ${UNPRIV_UID} -g ${UNPRIV_GID} -s /usr/sbin/nologin sandbox

# Create workdir and install minimal dependencies
WORKDIR /workspace

RUN apt-get update && \
    apt-get install -y --no-install-recommends tini ca-certificates && \
    apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false && \
    rm -rf /var/lib/apt/lists/*

# Copy runner
COPY runner.py /usr/local/bin/runner.py
RUN chown sandbox:sandbox /usr/local/bin/runner.py && \
    chmod +x /usr/local/bin/runner.py

USER sandbox
ENV HOME=/home/sandbox

ENTRYPOINT ["/usr/bin/tini", "--", "python", "/usr/local/bin/runner.py"]