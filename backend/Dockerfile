# Python 3.13, а не 3.14: к этапу 6 понадобится PyTorch под CUDA 12.8
# для локальных эмбеддингов, а он отстаёт от свежих версий Python.
FROM python:3.13-slim

# Без этого stdout в контейнере блочно буферизуется (не tty), и логи —
# включая трейсбеки 500-х — не долетают до `docker compose logs` до перезапуска процесса.
ENV PYTHONUNBUFFERED=1

# PDF уроков собирается Typst прямо в запросе экспорта (`app/lessons/export/pdf.py`).
# Та же проверенная сборка, что в Dockerfile.worker.
ARG TYPST_VERSION=0.15.1
ARG TYPST_SHA256=a6d077d0a95eed5a2eba715b2dae06be954f624ccbf85758a03f389ded33118c

RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends curl xz-utils \
    && curl --fail --location --silent --show-error \
      "https://github.com/typst/typst/releases/download/v${TYPST_VERSION}/typst-x86_64-unknown-linux-musl.tar.xz" \
      --output /tmp/typst.tar.xz \
    && echo "${TYPST_SHA256}  /tmp/typst.tar.xz" | sha256sum --check --status \
    && tar --extract --xz --file /tmp/typst.tar.xz --strip-components=1 \
      --directory /tmp "typst-x86_64-unknown-linux-musl/typst" \
    && install -m 0755 /tmp/typst /usr/local/bin/typst \
    && rm -f /tmp/typst /tmp/typst.tar.xz \
    && apt-get purge -y -qq curl xz-utils && apt-get autoremove -y -qq \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
