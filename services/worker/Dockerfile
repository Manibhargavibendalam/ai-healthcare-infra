# Pinned exact patch, verified on Docker Hub (M3). Digest-pinning is the prod step.
FROM python:3.12.14-slim
RUN useradd -m appuser
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY worker.py .
USER appuser
CMD ["python", "worker.py"]
