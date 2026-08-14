FROM python:3.11-slim

WORKDIR /srv

COPY pyproject.toml README.md ./
COPY app ./app
COPY policy ./policy

RUN pip install --no-cache-dir .

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"

# --no-access-log: the app emits its own structured JSON request logs
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
