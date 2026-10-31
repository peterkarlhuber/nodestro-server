# The Nodestro server image: `nodestro-server` (API, worker, operator commands) with the studio interface.
#
#   docker buildx build -f image/Dockerfile --build-arg STUDIO_COMMIT=<sha> \
#       --secret id=nodestro_read,env=NODESTRO_READ -t nodestro-server .
#
# STUDIO_COMMIT is a merge commit of nodestro-studio (studio.json); it pins every component by full commit SHA.
# The component repositories are private: the build reads them with the token in the `nodestro_read` secret,
# which never enters a layer. Behind a TLS-inspecting proxy, pass its certificate authority as the `build_ca`
# secret (and the proxy variables as build arguments). Nothing is fetched when a container starts.

ARG PYTHON_VERSION=3.13
ARG NODE_VERSION=22

# ---- development only: wheels that replace pinned components (--build-context overrides=DIR) ------
# Empty unless a build passes the context; release images never do (scripts/build-image.sh refuses it).
FROM scratch AS overrides

# ---- the studio source and its built interface ---------------------------------------------------
FROM node:${NODE_VERSION}-bookworm-slim AS studio
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
    rm -rf .git
RUN --mount=type=secret,id=build_ca \
    set -eu; \
    if [ -s /run/secrets/build_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca; fi; \
    cd frontend && npm ci --no-audit --no-fund && npm run build && rm -rf node_modules; \
    test -f /src/src/nodestro_studio/static/index.html

# ---- the Python environment --------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS build
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
    /opt/nodestro/venv/bin/python /install.py; \
    /opt/nodestro/venv/bin/pip freeze --disable-pip-version-check > /opt/nodestro/pinned.txt
RUN --mount=type=bind,from=overrides,target=/overrides \
    set -eu; \
    if ls /overrides/*.whl >/dev/null 2>&1; then \
      echo "development build: replacing pinned components with $(ls /overrides)"; \
      /opt/nodestro/venv/bin/pip install --no-deps --force-reinstall --no-cache-dir --disable-pip-version-check /overrides/*.whl; \
      echo "development build" > /opt/nodestro/overridden.txt; \
    fi; \
    /opt/nodestro/venv/bin/pip uninstall --yes --disable-pip-version-check pip; \
    find /opt/nodestro/venv -type d -name __pycache__ -prune -exec rm -rf {} +; \
    /opt/nodestro/venv/bin/python -I -c "import nodestro_api.server, nodestro_studio.app, psycopg, cryptography, jwt"

# ---- the image -----------------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim
ARG PYTHON_VERSION
ARG TARGETARCH
# The docker CLI talks to the sandbox's Docker daemon (DOCKER_HOST); the daemon itself is not in this image.
ARG DOCKER_CLI_VERSION=29.9.2
ARG DOCKER_CLI_SHA256_AMD64=9ac225999fd5e863f7694c728ef23d480616b1e5639328fa309befd4243d69eb
ARG DOCKER_CLI_SHA256_ARM64=873b3e0207857c3b2f28392fb922f3ea6efe37620c16d4d4aaf2fef409c90b73
RUN --mount=type=secret,id=build_ca \
    set -eu; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl postgresql-client tini; \
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
COPY --from=build /opt/nodestro /opt/nodestro
RUN useradd --system --uid 10001 --home-dir /var/lib/nodestro --create-home nodestro
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
