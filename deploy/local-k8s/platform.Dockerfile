FROM node:22-alpine AS frontend
WORKDIR /source/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
COPY . /app
COPY --from=frontend /source/frontend/dist /app/frontend/dist
RUN pip install --no-cache-dir '.[platform]'
ENV EVAL_LOOM_DATA_DIR=/data
ENV EVAL_LOOM_FRONTEND_DIST=/app/frontend/dist
EXPOSE 8787
CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8787"]
