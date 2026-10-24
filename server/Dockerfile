FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY server/requirements-lock.txt ./requirements-lock.txt
RUN pip install --no-cache-dir -r requirements-lock.txt

COPY server/ ./server/
COPY examples/ ./examples/

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]
