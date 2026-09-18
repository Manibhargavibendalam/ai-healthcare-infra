# Pinned exact patch, verified on Docker Hub (M3). Digest-pinning is the prod step.
FROM python:3.12.14-slim
RUN useradd -m appuser
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
USER appuser
EXPOSE 8002
# 2 workers: a hung /sync (timeout mode) must not block the /mode control endpoint.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002", "--workers", "2"]
