FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN mkdir -p /data
ENV HOST=0.0.0.0 PORT=8080 SCOREBOARD_DB=/data/scoreboard.db
EXPOSE 8080
CMD ["python", "-m", "backend.server"]
