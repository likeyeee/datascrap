FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY scout ./scout
COPY config ./config
COPY extension ./extension
RUN mkdir -p /app/data

EXPOSE 8000
CMD ["python", "-m", "scout", "serve", "--host", "0.0.0.0", "--port", "8000"]
