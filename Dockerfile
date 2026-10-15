FROM python:3.13-alpine
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8787 AICS_DB_PATH=/data/studio.sqlite3
WORKDIR /app
COPY server.py ./
COPY dist ./dist
RUN mkdir -p /data && addgroup -S studio && adduser -S -G studio studio && chown -R studio:studio /app /data
USER studio
EXPOSE 8787
CMD ["python", "server.py"]
