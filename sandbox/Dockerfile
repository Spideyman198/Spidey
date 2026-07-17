# Hardened execution image (ADR-0007, docs/11 B4).
#
# Runs untrusted repository code. Kept minimal and non-root; all runtime
# hardening (network none, read-only rootfs, cgroup caps, dropped capabilities,
# no-new-privileges, tmpfs) is applied per-container by DockerSandbox — this
# image only provides the toolchain and a rootless default user. It carries no
# secrets, no Docker client, and no network daemons.
#
# Pin by digest in production (the deploy pipeline rewrites the tag → sha256).
FROM python:3.12-slim-bookworm

# Toolchains the Tester/Terminal agents need, plus git for read-only VCS ops.
# No package manager is invoked at runtime; installs happen only via the
# approval-gated egress proxy, never from inside a default (network-none) run.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        ca-certificates \
        nodejs \
        npm \
    && rm -rf /var/lib/apt/lists/*

# A fixed, unprivileged UID. DockerSandbox runs containers as this user; the
# read-only rootfs means it can only write the mounted workspace and /tmp tmpfs.
RUN useradd --uid 65532 --create-home --home-dir /home/runner --shell /usr/sbin/nologin runner

# Test runners live in the image so a network-none run needs no installs.
RUN pip install --no-cache-dir pytest==8.3.4

WORKDIR /workspace
USER 65532

# No ENTRYPOINT/CMD that runs on its own: the sandbox always supplies an explicit
# argv. A container with no command is inert.
CMD ["true"]
