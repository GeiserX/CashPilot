FROM debian:bookworm-slim@sha256:e67eeead736ff7bbe258ef088bff683635c561b1fcfefad0806c1df4ab49ce0e

RUN test "$(dpkg --print-architecture)" = amd64 \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && install -d -o 10001 -g 10001 -m 0750 /var/lib/krig

COPY VERSION ARCHIVE_SHA256 BINARY_SHA256 /usr/local/share/krig/
COPY --chmod=0555 entrypoint.sh /usr/local/bin/krig-entrypoint

ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility
VOLUME ["/var/lib/krig"]
USER 10001:10001
ENTRYPOINT ["/usr/local/bin/krig-entrypoint"]
CMD ["--version"]
