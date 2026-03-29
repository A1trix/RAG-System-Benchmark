FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        poppler-utils \
        libxml2 \
        libxslt1.1 \
        libjpeg62-turbo \
        zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY rag_service/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY rag_service/ /app/rag_service/
RUN chmod +x /app/rag_service/start.sh

EXPOSE 8080

CMD ["/app/rag_service/start.sh"]
