# The Nodestro container images, built from one definition with two operating profiles:
#
# - target `server` (the default, the last stage): `nodestro-server` (API, worker, operator commands) with the studio
#   interface, PostgreSQL client and the server extras;
# - target `local`: Nodestro Local Docker (`nodestro-local`, profile `local-container`): the same studio and Python
#   environment without the server extras, plus the same docker CLI, which talks only to the sandbox gateway
#   (nodestro_runtime.sandbox_gateway, run from this image as its own container). Built by the
#   nodestro-local-docker repository.
#
#   docker buildx build -f image/Dockerfile --build-arg STUDIO_COMMIT=<sha> [--target local] -t nodestro-server .
#
# STUDIO_COMMIT is a merge commit of nodestro-studio (studio.json); it pins every component by full commit SHA.
# The component repositories are public, so no token is needed; a token in the optional `nodestro_read` secret
# (never a layer) is still used when given. Behind a TLS-inspecting proxy, pass its certificate authority as the `build_ca`
# secret (and the proxy variables as build arguments). Nothing is fetched when a container starts.

ARG PYTHON_VERSION=3.13
# The base images by the digest of their multi-platform index, so that a rebuild of the same commits uses the same
# operating system layers (amd64 and arm64). PYTHON_IMAGE must be PYTHON_VERSION (the stages check the paths). Update
# both on purpose: docker buildx imagetools inspect python:3.13-slim (or node:22-bookworm-slim).
ARG PYTHON_IMAGE=python:3.13-slim@sha256:2d44738ebf4ce5f63b9d9ea871e9c7cfdc0426f7b0c97cac915fd88ded1d86bb
ARG NODE_IMAGE=node:22-bookworm-slim@sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da

# ---- development only: wheels that replace pinned components (--build-context overrides=DIR) ------
# Empty unless a build passes the context; release images never do (scripts/build-image.sh refuses it).
FROM scratch AS overrides

# ---- the studio source and its built interface ---------------------------------------------------
FROM ${NODE_IMAGE} AS studio
ARG STUDIO_COMMIT
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN --mount=type=secret,id=nodestro_read --mount=type=secret,id=build_ca \
    set -eu; \
    test -n "${STUDIO_COMMIT}" || { echo "STUDIO_COMMIT is required" >&2; exit 1; }; \
    if [ -s /run/secrets/build_ca ]; then export GIT_SSL_CAINFO=/run/secrets/build_ca; fi; \
    if [ -s /run/secrets/nodestro_read ]; then \
      export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0="url.https://x-access-token:$(cat /run/secrets/nodestro_read)@github.com/peterkarlhuber/.insteadOf" \
        GIT_CONFIG_VALUE_0="https://github.com/peterkarlhuber/"; \
    fi; \
    git init -q . && git remote add origin https://github.com/peterkarlhuber/nodestro-studio.git; \
    git fetch -q --depth 1 origin "${STUDIO_COMMIT}" && git checkout -q FETCH_HEAD; \
    git rev-parse HEAD > /src/.studio-commit; \
    rm -rf .git
COPY scripts/npm_licenses.mjs /npm_licenses.mjs
RUN --mount=type=secret,id=build_ca \
    set -eu; \
    if [ -s /run/secrets/build_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca; fi; \
    cd frontend && npm ci --no-audit --no-fund && npm run build; \
    node /npm_licenses.mjs . > /src/THIRD-PARTY-npm.txt; \
    rm -rf node_modules; \
    test -f /src/src/nodestro_studio/static/index.html

# ---- the Python environment (both profiles) ----------------------------------------------------
FROM ${PYTHON_IMAGE} AS build
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=studio /src /src
COPY image/install.py /install.py
RUN --mount=type=secret,id=nodestro_read --mount=type=secret,id=build_ca \
    set -eu; \
    if [ -s /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca GIT_SSL_CAINFO=/run/secrets/build_ca; fi; \
    if [ -s /run/secrets/nodestro_read ]; then \
      export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0="url.https://x-access-token:$(cat /run/secrets/nodestro_read)@github.com/peterkarlhuber/.insteadOf" \
        GIT_CONFIG_VALUE_0="https://github.com/peterkarlhuber/"; \
    fi; \
    python -m venv /opt/nodestro/venv; \
    /opt/nodestro/venv/bin/pip install --no-cache-dir --disable-pip-version-check /src; \
    mkdir -p /opt/nodestro/meta; \
    cp /src/.studio-commit /opt/nodestro/meta/studio-commit; \
    cp /src/platform/versions.json /src/frontend/package-lock.json /opt/nodestro/meta/; \
    mkdir -p /opt/nodestro/licenses; \
    cp /src/LICENSE /opt/nodestro/licenses/LICENSE-nodestro.txt; \
    cp /src/THIRD-PARTY-npm.txt /opt/nodestro/licenses/; \
    printf '%s\n' \
      "Nodestro is MIT licensed (LICENSE-nodestro.txt). It contains third-party software under its own licenses:" \
      "- THIRD-PARTY-npm.txt: the npm packages built into the studio interface;" \
      "- each Python package's license is in its /opt/nodestro/venv/lib/python*/site-packages/*.dist-info directory;" \
      "- the Debian packages of the base image: /usr/share/doc/*/copyright;" \
      "- the docker CLI (/usr/local/bin/docker): Apache-2.0, https://github.com/docker/cli/blob/master/LICENSE." \
      > /opt/nodestro/licenses/README.txt
COPY image/finalize.sh /finalize.sh

# The server's environment: the server extras at exactly the pinned commits.
FROM build AS server-env
RUN --mount=type=secret,id=nodestro_read --mount=type=secret,id=build_ca \
    set -eu; \
    if [ -s /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca GIT_SSL_CAINFO=/run/secrets/build_ca; fi; \
    if [ -s /run/secrets/nodestro_read ]; then \
      export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0="url.https://x-access-token:$(cat /run/secrets/nodestro_read)@github.com/peterkarlhuber/.insteadOf" \
        GIT_CONFIG_VALUE_0="https://github.com/peterkarlhuber/"; \
    fi; \
    /opt/nodestro/venv/bin/python /install.py
RUN --mount=type=bind,from=overrides,target=/overrides \
    sh /finalize.sh "import nodestro_api.server, nodestro_studio.app, psycopg, cryptography, jwt"

# Nodestro Local Docker's environment: the studio as pinned, no server extras.
FROM build AS local-env
RUN --mount=type=bind,from=overrides,target=/overrides \
    sh /finalize.sh "import nodestro_api.local_container, nodestro_studio.app, nodestro_runtime.sandbox_gateway"

# ---- what both images share: tini and the docker CLI -----------------------------------------------
FROM ${PYTHON_IMAGE} AS base
ARG TARGETARCH
# The docker CLI talks to the sandbox's Docker daemon (DOCKER_HOST); the daemon itself is not in this image.
ARG DOCKER_CLI_VERSION=29.9.2
ARG DOCKER_CLI_SHA256_AMD64=9ac225999fd5e863f7694c728ef23d480616b1e5639328fa309befd4243d69eb
ARG DOCKER_CLI_SHA256_ARM64=873b3e0207857c3b2f28392fb922f3ea6efe37620c16d4d4aaf2fef409c90b73
RUN --mount=type=secret,id=build_ca \
    set -eu; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl tini; \
    case "${TARGETARCH:-amd64}" in \
      amd64) arch=x86_64; sum="${DOCKER_CLI_SHA256_AMD64}" ;; \
      arm64) arch=aarch64; sum="${DOCKER_CLI_SHA256_ARM64}" ;; \
      *) echo "unsupported architecture ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    cafile=""; if [ -s /run/secrets/build_ca ]; then cafile="--cacert /run/secrets/build_ca"; fi; \
    curl -fsSL $cafile -o /tmp/docker.tgz "https://download.docker.com/linux/static/stable/${arch}/docker-${DOCKER_CLI_VERSION}.tgz"; \
    echo "${sum}  /tmp/docker.tgz" | sha256sum -c -; \
    tar -xzf /tmp/docker.tgz -C /usr/local/bin --strip-components=1 docker/docker; \
    rm /tmp/docker.tgz; \
    apt-get purge -y curl; apt-get autoremove -y; rm -rf /var/lib/apt/lists/*; \
    docker --version
RUN useradd --system --uid 10001 --home-dir /var/lib/nodestro --create-home nodestro

# ---- Nodestro Local Docker (target `local`) -------------------------------------------------------
# One person, SQLite in /var/lib/nodestro, the studio on port 8080 of the container (the compose file publishes it
# on the host's loopback only), an access key created on first start, tool code only in sandbox containers through
# the gateway's socket. The gateway container runs this image with `gateway` (as root, without capabilities or
# network, the only container with the host's Docker socket).
FROM base AS local
ARG PYTHON_VERSION
COPY --from=local-env /opt/nodestro /opt/nodestro
ENV PATH=/opt/nodestro/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NODESTRO_PROFILE=local-container \
    NODESTRO_DATA_DIR=/var/lib/nodestro/data \
    NODESTRO_ACCESS_KEY_FILE=/var/lib/nodestro/secrets/access-key \
    DOCKER_HOST=unix:///run/nodestro-sandbox/docker.sock \
    DOCKER_BUILDKIT=0 \
    NODESTRO_STATIC_DIR=/opt/nodestro/venv/lib/python${PYTHON_VERSION}/site-packages/nodestro_studio/static \
    NODESTRO_DOCS_DIR=/opt/nodestro/venv/lib/python${PYTHON_VERSION}/site-packages/nodestro_studio/docs
RUN test -f "${NODESTRO_STATIC_DIR}/index.html" && test -d "${NODESTRO_DOCS_DIR}/en" \
    && mkdir -p /var/lib/nodestro/data /var/lib/nodestro/secrets /run/nodestro-sandbox \
    && chown -R 10001:10001 /var/lib/nodestro && chmod 0700 /var/lib/nodestro/secrets
USER 10001:10001
WORKDIR /var/lib/nodestro
VOLUME ["/var/lib/nodestro"]
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=6 \
    CMD ["python", "-I", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=4)"]
ENTRYPOINT ["tini", "--", "nodestro-local"]
CMD ["serve"]

# ---- the server (target `server`, the default) ----------------------------------------------------
FROM base AS server
ARG PYTHON_VERSION
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client && rm -rf /var/lib/apt/lists/*
COPY --from=server-env /opt/nodestro /opt/nodestro
ENV PATH=/opt/nodestro/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NODESTRO_PROFILE=server \
    NODESTRO_DATA_DIR=/var/lib/nodestro \
    NODESTRO_STATIC_DIR=/opt/nodestro/venv/lib/python${PYTHON_VERSION}/site-packages/nodestro_studio/static \
    NODESTRO_DOCS_DIR=/opt/nodestro/venv/lib/python${PYTHON_VERSION}/site-packages/nodestro_studio/docs
RUN test -f "${NODESTRO_STATIC_DIR}/index.html" && test -d "${NODESTRO_DOCS_DIR}/en"
USER 10001:10001
WORKDIR /var/lib/nodestro
VOLUME ["/var/lib/nodestro"]
EXPOSE 8080
ENTRYPOINT ["tini", "--", "nodestro-server"]
CMD ["check"]
