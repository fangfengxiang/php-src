FROM php:8.2-cli-bookworm@sha256:ac125c2d3ce1e8e33b503bcf85bdea9b43ed108515134629163a5971b3c9ac85

# This image supplies build tools only. PHP 7.0 is built from the reviewed
# checkout, never from the PHP 8 binary supplied by the base image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        autoconf2.69 bison clang libxml2-dev libsqlite3-dev python3 zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# PHP 7.0's custom parser diagnostics use yystrlen/yystpcpy, which the Bison
# 3.8 skeleton no longer emits. Keep parser generation on a compatible release.
RUN curl -fsSL https://ftp.gnu.org/gnu/bison/bison-3.5.1.tar.xz -o /tmp/bison.tar.xz \
    && echo '3e7e097bd9709a2d5e40e69446b74b149733b3de864fadb7a9b54eca7b2a4dd0  /tmp/bison.tar.xz' | sha256sum -c - \
    && tar -xJf /tmp/bison.tar.xz -C /tmp \
    && cd /tmp/bison-3.5.1 \
    && ./configure --prefix=/opt/bison --disable-nls \
    && make -j4 \
    && make install \
    && rm -rf /tmp/bison-3.5.1 /tmp/bison.tar.xz

ENV PATH="/opt/bison/bin:${PATH}"

WORKDIR /work
