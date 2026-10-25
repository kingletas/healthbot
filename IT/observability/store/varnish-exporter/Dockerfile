# varnishstat has to match the Varnish that wrote the shared memory, so the exporter is added to the
# store's own Varnish image rather than shipped with a varnishstat of its own.
ARG VARNISH_IMAGE=varnish:8.0
FROM ${VARNISH_IMAGE}

ARG EXPORTER_VERSION=1.6.1
ARG EXPORTER_SHA256
USER root
RUN set -eu; \
    test -n "${EXPORTER_SHA256}"; \
    name="prometheus_varnish_exporter-${EXPORTER_VERSION}.linux-amd64"; \
    curl -fsSL -o /tmp/exporter.tar.gz \
        "https://github.com/jonnenauha/prometheus_varnish_exporter/releases/download/${EXPORTER_VERSION}/${name}.tar.gz"; \
    echo "${EXPORTER_SHA256}  /tmp/exporter.tar.gz" | sha256sum -c -; \
    tar -xzf /tmp/exporter.tar.gz -C /tmp; \
    install -m 0755 "/tmp/${name}/prometheus_varnish_exporter" /usr/local/bin/; \
    rm -r /tmp/exporter.tar.gz "/tmp/${name}"
USER varnish
ENTRYPOINT ["/usr/local/bin/prometheus_varnish_exporter", "-n", "/var/lib/varnish/varnishd", "-web.listen-address", ":9131"]
