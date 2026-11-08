FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY tradebot ./tradebot
RUN pip install --no-cache-dir .
ENV WEB_HOST=0.0.0.0 DB_PATH=/data/tradebot.sqlite3
VOLUME ["/data"]
EXPOSE 8000
CMD ["tradebot", "run"]
