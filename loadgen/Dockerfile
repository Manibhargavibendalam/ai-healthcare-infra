# Load generator (test tooling, not a microservice). Headless only.
# Pinned exact patch, verified on PyPI (M5).
FROM python:3.12.14-slim
RUN useradd -m appuser
WORKDIR /load
COPY requirements.txt locustfile.py ./
RUN pip install --no-cache-dir -r requirements.txt
USER appuser
ENTRYPOINT ["locust"]
