# Non-final candidate only. "extractor" is a separate, digest-verified named
# build context containing extractor.spkg and extractor-lock.json.
FROM rust:1.98.0-bookworm@sha256:4e4a7e7939c17991ab35f2b8c2e67593980f771d28f6b1254b1850f860fd0c7f AS builder
ARG SOURCE_COMMIT
WORKDIR /build
COPY . .
COPY --from=extractor / /extractor/
RUN cargo run --locked --package xtask -- producer-runtime verify-source --root /build --revision "$SOURCE_COMMIT" \
    && cargo run --locked --package xtask -- producer-runtime build-bundle \
       --root /build --spkg /extractor/extractor.spkg \
       --extractor-lock /extractor/extractor-lock.json --output /payload

FROM debian:bookworm-slim@sha256:5ae3c39ebd15e229dcedd5cee596b2497182493d41ff162e824ba13fc1b2b867
RUN groupadd --gid 10001 producer \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin producer
COPY --from=builder --chown=10001:10001 /payload/ /opt/producer/
ARG SOURCE_COMMIT
LABEL org.opencontainers.image.source="https://github.com/pinax-network/substreams-backfills" \
      org.opencontainers.image.revision="${SOURCE_COMMIT}" \
      org.opencontainers.image.title="Aerodrome development producer" \
      network.pinax.production-selectable="false"
USER 10001:10001
WORKDIR /opt/producer
ENTRYPOINT ["/opt/producer/bin/producer"]
CMD ["version", "--json"]
