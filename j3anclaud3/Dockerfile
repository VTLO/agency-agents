# Build from the repository root so the agent library is included:
#   docker build -f j3anclaud3/Dockerfile -t j3anclaud3 .
FROM python:3.12-slim

WORKDIR /srv/agency
# One COPY per directory: a multi-source COPY would flatten them.
COPY academic ./academic
COPY design ./design
COPY engineering ./engineering
COPY game-development ./game-development
COPY marketing ./marketing
COPY paid-media ./paid-media
COPY product ./product
COPY project-management ./project-management
COPY sales ./sales
COPY spatial-computing ./spatial-computing
COPY specialized ./specialized
COPY support ./support
COPY testing ./testing
COPY j3anclaud3 ./j3anclaud3

RUN pip install --no-cache-dir ./j3anclaud3 && mkdir -p /data && chown nobody /data

ENV J3_AGENCY_ROOT=/srv/agency \
    J3_DATA_DIR=/data \
    PORT=8080 \
    HOST=0.0.0.0
VOLUME ["/data"]
EXPOSE 8080
USER nobody
CMD ["j3anclaud3", "serve"]
