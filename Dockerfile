FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server server
COPY web web
COPY verifier verifier
COPY scripts scripts
COPY prompts prompts
COPY schema schema
COPY data data
ENV PORT=8080
CMD exec python -m uvicorn server.main:app --host 0.0.0.0 --port ${PORT}
