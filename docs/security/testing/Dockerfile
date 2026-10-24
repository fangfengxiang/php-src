ARG BASE_IMAGE=debian:12
FROM ${BASE_IMAGE}

# This image supplies build tools only and contains no preinstalled PHP.
# Build and test PHP 7.0 from the reviewed branch, using /work/install/bin/php.
RUN apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20 update \
    && apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20 install -y --no-install-recommends \
        autoconf2.69 build-essential ca-certificates curl re2c xz-utils \
        libxml2-dev libsqlite3-dev python3 zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# PHP 7.0's custom parser diagnostics use yystrlen/yystpcpy, which the Bison
# 3.8 skeleton no longer emits. Keep parser generation on a compatible release.
RUN set -eu; \
    for bison_url in \
        https://mirrors.kernel.org/gnu/bison/bison-3.5.1.tar.xz \
        https://ftp.gnu.org/gnu/bison/bison-3.5.1.tar.xz; do \
        if curl -fsSL --connect-timeout 10 --max-time 45 \
            --retry 1 --retry-delay 1 --retry-max-time 60 \
            "$bison_url" -o /tmp/bison.tar.xz; then break; fi; \
    done; \
    echo '3e7e097bd9709a2d5e40e69446b74b149733b3de864fadb7a9b54eca7b2a4dd0  /tmp/bison.tar.xz' | sha256sum -c - \
    && tar -xJf /tmp/bison.tar.xz -C /tmp \
    && cd /tmp/bison-3.5.1 \
    && ./configure --prefix=/opt/bison --disable-nls \
    && make -j4 \
    && make install \
    && rm -rf /tmp/bison-3.5.1 /tmp/bison.tar.xz

ENV PATH="/opt/bison/bin:${PATH}"

WORKDIR /work
