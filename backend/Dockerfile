# Python 3.13, а не 3.14: к этапу 6 понадобится PyTorch под CUDA 12.8
# для локальных эмбеддингов, а он отстаёт от свежих версий Python.
FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
