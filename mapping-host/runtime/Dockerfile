# Build only the committed, allowlisted context exported by package.py context.
FROM rust:1.98.0-bookworm@sha256:4e4a7e7939c17991ab35f2b8c2e67593980f771d28f6b1254b1850f860fd0c7f AS builder
RUN apt-get update && apt-get install -y --no-install-recommends libpq-dev protobuf-compiler python3 && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY . .
RUN python3 mapping-host/runtime/package.py verify-source --root /build
RUN cargo build --manifest-path mapping-host/Cargo.toml --locked --release --bin graph-mapping-host
RUN install -D -m 0555 mapping-host/target/release/graph-mapping-host /payload/usr/local/bin/graph-mapping-host \
    && mkdir -p /payload/opt/mapping-host \
    && cp -a mapping-host/segments /payload/opt/mapping-host/segments \
    && cp source.json /payload/opt/mapping-host/source.json \
    && python3 mapping-host/runtime/package.py seal --root /payload

FROM debian:bookworm-slim@sha256:5ae3c39ebd15e229dcedd5cee596b2497182493d41ff162e824ba13fc1b2b867 AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 mapping-host \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin mapping-host
COPY --from=builder --chown=10001:10001 /payload/ /
ARG SOURCE_COMMIT
LABEL org.opencontainers.image.source="https://github.com/pinax-network/substreams-backfills" \
      org.opencontainers.image.revision="${SOURCE_COMMIT}" \
      org.opencontainers.image.title="Uniswap V3 mapping-host execution runtime" \
      network.pinax.production-selectable="false"
USER 10001:10001
WORKDIR /opt/mapping-host
ENTRYPOINT ["/usr/local/bin/graph-mapping-host"]
CMD ["--help"]
