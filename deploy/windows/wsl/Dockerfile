# Rouh's own WSL Linux (task 186, step 186-04): the Linux that Rouh for Windows imports into WSL2
# (Windows' built-in Linux layer), as a .wsl file. Debian 13 with Docker Engine (never Docker
# Desktop), systemd on, the `rouh-wsl` helper the Windows side talks to, and nothing of Rouh itself:
# Rouh's updater, its release and its images are fetched and checked on the first start, by the
# same https://rouh.land/install.sh a Linux server runs, so Windows runs exactly the Linux stack.
#
# Built by build.sh (docker build, then docker export of the result as the .wsl), at GitHub for
# x64 and Arm (.github/workflows/wsl-image.yml). Locked down as 186-02 found OpenClaw's own distro
# is: no Windows drives mounted, no Windows programs runnable from inside, no general sudo.
ARG DEBIAN_IMAGE=debian:trixie-slim@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2
FROM ${DEBIAN_IMAGE}

ARG TARGETARCH
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8

# What install.sh and the rouh command need, systemd (WSL starts it with systemd=true), and Docker
# Engine with Compose from Docker's own Debian packages, checked by Docker's signing key.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      systemd systemd-sysv dbus dbus-user-session libpam-systemd ca-certificates curl gnupg git openssl \
      python3 iproute2 iptables procps sudo less xz-utils; \
    install -m 0755 -d /etc/apt/keyrings; \
    curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc; \
    gpg --show-keys --with-colons /etc/apt/keyrings/docker.asc | grep -q '^fpr:::::::::9DC858229FC7DD38854AE2D88D81803C0EBFCD88:'; \
    echo "deb [arch=${TARGETARCH} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian trixie stable" \
      > /etc/apt/sources.list.d/docker.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends docker-ce docker-ce-cli containerd.io docker-compose-plugin; \
    apt-get purge -y gnupg; apt-get autoremove -y; \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/*.bin /var/log/*.log /var/log/apt/* /tmp/* /root/.cache

# The person's Linux account. No password: nobody signs in to it; Windows opens it with
# `wsl -d Rouh`. Docker's group, which is how Rouh's own command reaches Docker on every Linux.
RUN set -eux; \
    useradd --create-home --uid 1000 --shell /bin/bash --groups docker rouh; \
    passwd -l rouh; passwd -l root; \
    systemctl enable docker.service containerd.service; \
    systemctl mask systemd-networkd-wait-online.service systemd-resolved.service getty@tty1.service \
      console-getty.service serial-getty@.service 2>/dev/null || true; \
    rm -f /etc/machine-id /var/lib/dbus/machine-id; touch /etc/machine-id

COPY files/ /
RUN set -eux; \
    chmod 0440 /etc/sudoers.d/rouh; visudo -cf /etc/sudoers.d/rouh; \
    chmod 0755 /usr/local/bin/rouh-wsl; \
    printf '%s\n' "built=$(date -u +%Y-%m-%dT%H:%M:%SZ)" "arch=${TARGETARCH}" "debian=$(cat /etc/debian_version)" \
      "docker=$(dpkg-query -W -f='${Version}' docker-ce)" "compose=$(dpkg-query -W -f='${Version}' docker-compose-plugin)" \
      "containerd=$(dpkg-query -W -f='${Version}' containerd.io)" "python=$(python3 -c 'import platform; print(platform.python_version())')" \
      > /etc/rouh-wsl-release
