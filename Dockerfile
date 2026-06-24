FROM miigotu/python3.11-slim:latest

LABEL org.opencontainers.image.title="Plex JAV Metadata Provider"
LABEL org.opencontainers.image.source="https://github.com/mikaelchan/plex-jav-metadata"

WORKDIR /app

ARG APT_MIRROR=mirrors.tuna.tsinghua.edu.cn
ARG PIP_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple

RUN sed -i "s@deb.debian.org@$APT_MIRROR@g" /etc/apt/sources.list.d/debian.sources 2>/dev/null; \
    sed -i "s@httpredir.debian.org@$APT_MIRROR@g" /etc/apt/sources.list 2>/dev/null; \
    sed -i "s@deb.debian.org@$APT_MIRROR@g" /etc/apt/sources.list 2>/dev/null; \
    apt-get update && apt-get install -y --no-install-recommends \
    git ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

COPY . /app/
RUN pip install --no-cache-dir -i $PIP_MIRROR -e .

RUN mkdir -p /data

EXPOSE 8800

ENV DATA_DIR=/data

CMD ["uvicorn", "api.__main__:app", "--host", "0.0.0.0", "--port", "8800"]
