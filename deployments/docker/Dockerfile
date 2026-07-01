# ============================================================
# LangGraph Cluster — 单镜像多角色 Docker 构建
#
# 镜像包含全部代码，角色 (Gateway / Worker / Scheduler) 由
# K8s Deployment 的 command/args 在运行时指定，无需多份 Dockerfile。
# ============================================================

# ---- 依赖安装阶段 ----
FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir poetry==1.8.3

COPY pyproject.toml poetry.lock* ./

RUN poetry config virtualenvs.create false \
    && poetry install --only main --no-interaction --no-ansi --no-root

# ---- 运行阶段 ----
FROM python:3.12-slim AS runtime

WORKDIR /app

RUN groupadd -r langgraph && useradd -r -g langgraph langgraph

# 安装 curl (HEALTHCHECK 需要)
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 复制全部应用代码 (角色在运行时通过 command 切换)
COPY gateway/ ./gateway/
COPY orchestrator/ ./orchestrator/
COPY capabilities/ ./capabilities/
COPY infrastructure/ ./infrastructure/
COPY common/ ./common/

RUN chown -R langgraph:langgraph /app
USER langgraph

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

EXPOSE 8000

# 默认启动 Gateway (本地/单机模式)
# 集群模式下由 K8s Deployment 的 command/args 覆盖:
#   Gateway:   command: ["uvicorn"]  args: ["gateway.app:app", "--host", "0.0.0.0", "--port", "8000"]
#   Worker:    command: ["celery"]   args: ["-A", "infrastructure.queue.task_queue", "worker", "--loglevel=info", "--concurrency=4"]
#   Scheduler: command: ["celery"]   args: ["-A", "infrastructure.queue.task_queue", "beat", "--loglevel=info"]
CMD ["uvicorn", "gateway.app:app", "--host", "0.0.0.0", "--port", "8000"]
