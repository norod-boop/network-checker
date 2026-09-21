FROM python:3.12-alpine

ENV PYTHONUNBUFFERED=1 \
    NAMESPACE_NAME=default

WORKDIR /app

RUN apk add --no-cache iputils \
    && pip install --no-cache-dir kubernetes

COPY network-checker.py .

ENTRYPOINT ["python3", "network-checker.py"]
