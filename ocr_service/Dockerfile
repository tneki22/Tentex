FROM ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddleocr-vl:paddleocr3.5-nvidia-gpu-sm120

USER root
WORKDIR /service
# Keep the tested CUDA/Paddle runtime from the official image and pin the public
# pipeline adapter used by PP-StructureV3.
RUN python -m pip install --no-cache-dir \
    "paddleocr==3.7.0" \
    "fastapi>=0.115,<1" \
    "uvicorn[standard]>=0.34,<1"
COPY app.py /service/app.py

ENV PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
ENV PADDLE_PDX_MODEL_SOURCE=aistudio
ENV TENTEX_TEXTBOOK_DEVICE=gpu
ENV HOME=/root
ENV HF_HUB_DISABLE_XET=0
ENV HF_XET_HIGH_PERFORMANCE=1

CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090", "--workers", "1"]
