FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY finn ./finn
COPY engine ./engine
COPY api ./api
COPY ingest ./ingest
COPY deploy ./deploy
COPY data/mock ./data/mock
COPY data/cache/demo_sources ./data/cache/demo_sources
ENV FINN_DATABASE_PATH=/var/data/finn.sqlite FINN_CACHE_PATH=/var/data/cache
CMD ["python", "-m", "deploy.start_api"]
