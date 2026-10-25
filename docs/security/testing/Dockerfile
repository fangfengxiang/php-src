ARG BASE_IMAGE=debian:12
FROM ${BASE_IMAGE}

# This image supplies build tools only and contains no preinstalled PHP.
# Build and test PHP 7.0 from the reviewed branch, using /work/install/bin/php.
RUN set -eu; \
    . /etc/os-release; \
    case "$ID:$VERSION_ID" in \
      centos:7) \
        sed -i -e '/^mirrorlist=/d' \
          -e 's|^#baseurl=http://mirror.centos.org/centos/$releasever/|baseurl=https://vault.centos.org/7.9.2009/|' \
          /etc/yum.repos.d/CentOS-*.repo ;; \
      centos:8) \
        sed -i -e '/^mirrorlist=/d' \
          -e 's|^#baseurl=http://mirror.centos.org/$contentdir/$releasever/|baseurl=https://vault.centos.org/8.5.2111/|' \
          /etc/yum.repos.d/CentOS-Linux-*.repo ;; \
    esac; \
    if command -v apt-get >/dev/null; then \
      apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20 update; \
      apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20 install -y --no-install-recommends \
        autoconf2.69 build-essential ca-certificates curl re2c xz-utils \
        libxml2-dev libsqlite3-dev python3 zlib1g-dev; \
      rm -rf /var/lib/apt/lists/*; \
    else \
      set -- \
        autoconf gcc gcc-c++ make ca-certificates perl tar xz gzip diffutils findutils \
        libxml2-devel sqlite-devel python3 zlib-devel which; \
      if command -v dnf >/dev/null; then \
        dnf -y --setopt=install_weak_deps=False --setopt=timeout=20 --setopt=retries=2 install "$@"; \
        dnf clean all; \
      else \
        yum -y --setopt=timeout=20 --setopt=retries=2 install "$@"; \
        yum clean all; \
      fi; \
      autoconf --version | head -n 1 | grep '2\.69'; \
      ln -s /usr/bin/autoconf /usr/local/bin/autoconf2.69; \
      ln -s /usr/bin/autoheader /usr/local/bin/autoheader2.69; \
    fi

# RPM images build re2c at Debian 12's version without enabling EPEL or
# installing a distribution PHP package.
RUN set -eu; \
    if command -v re2c >/dev/null; then exit 0; fi; \
    curl -fsSL --connect-timeout 10 --max-time 45 \
      --retry 1 --retry-delay 1 --retry-max-time 60 \
      https://github.com/skvadrik/re2c/releases/download/3.0/re2c-3.0.tar.xz -o /tmp/re2c.tar.xz; \
    echo 'b3babbbb1461e13fe22c630a40c43885efcfbbbb585830c6f4c0d791cf82ba0b  /tmp/re2c.tar.xz' | sha256sum -c -; \
    tar -xJf /tmp/re2c.tar.xz -C /tmp; \
    cd /tmp/re2c-3.0; \
    ./configure --prefix=/opt/re2c --disable-docs; \
    make -j4; \
    make install; \
    rm -rf /tmp/re2c-3.0 /tmp/re2c.tar.xz

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

ENV PATH="/opt/bison/bin:/opt/re2c/bin:${PATH}"

WORKDIR /work
