# ARM64-only official Debian base; no preseeded source or build caches.
FROM debian:trixie-slim@sha256:da496358bd6934d2bd6a563a33176a2e50eff5490c54b4ac6fb051b69fef4071

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        bison build-essential bzip2 ca-certificates cpio curl file flex gawk \
        gettext git libelf-dev libncurses-dev libssl-dev patch perl pkgconf \
        python3 python3-dev python3-setuptools rsync swig time unzip util-linux \
        wget xz-utils zlib1g-dev zstd \
    && rm -rf /var/lib/apt/lists/*

# Debian trixie's go1.24.4 is below the current Go 1.27 bootstrap floor (1.24.6).
# Keep the external bootstrap separate from the feed-built final Go compiler.
ARG GO_VERSION=1.26.8
ARG GO_SHA256=211ffced9dcb9633a55eac6364816ec0ddd951389a740e88fa8b3337971bdda0
RUN test "$(dpkg --print-architecture)" = arm64 \
    && curl -fL --retry 3 "https://go.dev/dl/go${GO_VERSION}.linux-arm64.tar.gz" -o /tmp/go.tar.gz \
    && echo "${GO_SHA256}  /tmp/go.tar.gz" | sha256sum -c - \
    && tar -C /usr/lib -xzf /tmp/go.tar.gz \
    && rm /tmp/go.tar.gz \
    && /usr/lib/go/bin/go version

ENV PATH="/usr/lib/go/bin:${PATH}" \
    LANG=C.UTF-8
WORKDIR /bld
CMD ["sleep", "infinity"]
