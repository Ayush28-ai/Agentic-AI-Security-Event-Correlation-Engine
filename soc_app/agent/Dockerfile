FROM python:3.10-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV SERVER_URL=http://soc-server:8000
ENV SEND_INTERVAL=30
ENV DEVICE_NAME=""

CMD ["python", "pc_agent.py"]