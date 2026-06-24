FROM python:3.10-slim
WORKDIR /app

RUN apt-get update && apt-get install -y gcc git && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV MODEL_PATH=/app/data/soc_llm_phi3
ENV RAG_DB_PATH=/app/data/soc_rag_db
ENV DB_PATH=/app/shared/soc_incidents.db

EXPOSE 8000

CMD ["gunicorn","app:app","--workers","2","--worker-class","uvicorn.workers.UvicornWorker","--bind","0.0.0.0:8000","--timeout","120","--graceful-timeout","30","--keep-alive","5","--max-requests","100","--max-requests-jitter","10","--log-level","info"]