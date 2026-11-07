# syntax=docker/dockerfile:1.7
#
# rouh-guard: a Rouh's protected core (guard/README.md). The safety and repair
# parts a Rouh uses and cannot edit, updated only by the makers' signed releases.
#
# Small on purpose: Python from the same Debian release as the base, every
# Debian security update there is at build time, and the protected core's own
# files in /opt/rouh-guard. The key proxy runs on this image itself (standard
# library only); everything else is copied into the stack's guard-bin volume on
# each start (rouh-guard-install), which the base's containers mount read-only.
#
#   docker buildx build -f guard/Dockerfile -t rouh-guard .
#
# Built from the top of the repository; only guard/ is read (guard/Dockerfile.dockerignore).

ARG PYTHON_IMAGE=python:3.12.15-slim-trixie
FROM ${PYTHON_IMAGE}

ARG GUARD_LEVEL=dev
RUN apt-get update && apt-get -y upgrade && rm -rf /var/lib/apt/lists/*

COPY --chown=root:root guard /opt/rouh-guard
RUN find /opt/rouh-guard -name __pycache__ -prune -exec rm -rf {} + \
 && rm -rf /opt/rouh-guard/policy/fixtures \
 && chmod -R a+rX,go-w /opt/rouh-guard \
 && chmod 0755 /opt/rouh-guard/bin/* \
 && echo "level=${GUARD_LEVEL}" > /opt/rouh-guard/level.env

LABEL org.opencontainers.image.title="rouh-guard" \
      it.rouh.guard.level="${GUARD_LEVEL}"

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10002:10002
ENTRYPOINT ["python", "-I", "/opt/rouh-guard/rouh_guard/keyproxy.py"]
