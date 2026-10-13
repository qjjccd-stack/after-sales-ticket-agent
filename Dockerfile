FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TICKET_DB_PATH=/data/tickets.sqlite3
WORKDIR /app
COPY pyproject.toml requirements.lock.txt README.md LICENSE ./
COPY src ./src
COPY data/faq.json ./data/faq.json
COPY scripts ./scripts
RUN pip install --no-cache-dir -c requirements.lock.txt -e . \
    && useradd --create-home --uid 10001 ticket \
    && mkdir /data /backups && chown ticket:ticket /data /backups
USER ticket
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s CMD python -c "import os,urllib.request,urllib.parse; host=urllib.parse.urlsplit(os.getenv('APP_ORIGIN','http://127.0.0.1:8000')).netloc; urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000/health/ready',headers={'Host':host}),timeout=3)"
CMD ["python", "-m", "uvicorn", "react_agent.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
