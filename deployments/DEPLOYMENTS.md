# DEPLOYMENTS.md — 部署规范与约束

> **定位**: 定义 Docker 镜像构建、Kubernetes 集群拆分部署、资源配置和运维流程的约束规则。

**目录**: [集群架构](#1-集群架构) | [文件清单](#2-文件清单) | [Docker 规范](#3-docker-规范) | [Kubernetes 规范](#4-kubernetes-规范) | [弹性伸缩](#5-弹性伸缩) | [健康检查](#6-健康检查) | [密钥管理](#7-密钥管理) | [运维流程](#8-运维流程)

---

## 1. 集群架构

### 1.1 单镜像多角色架构

```
                         ┌──────────────────────────┐
                         │  同一个 Docker 镜像       │
                         │  (langgraph-app:latest)  │
                         │  ┌────────────────────┐  │
                         │  │ gateway/           │  │
                         │  │ orchestrator/      │  │
                         │  │ capabilities/      │  │
                         │  │ infrastructure/    │  │
                         │  │ common/            │  │
                         │  └────────────────────┘  │
                         └──────────┬───────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    │               │               │
              command:         command:         command:
        python -m gateway.app  celery worker    celery beat
                    │               │               │
                    ▼               ▼               ▼
          Gateway Cluster    Worker Cluster    Scheduler
          (3~10 Pods)        (3~50 Pods)       (1 Pod)
```

**角色完全由 K8s Deployment 的 `command`/`args` 区分，不需要多份 Dockerfile。**

### 1.2 容器启动命令 (单镜像多角色)

| 角色 | 镜像 | command | args | SERVICE_ROLE |
|------|------|---------|------|-------------|
| **Gateway** | `langgraph:latest` | `["uvicorn"]` | `["gateway.app:app", "--host", "0.0.0.0", "--port", "8000"]` | `gateway` |
| **Worker** | `langgraph:latest` | `["celery"]` | `["-A", "infrastructure.queue.task_queue", "worker", "--loglevel=info", "--concurrency=4"]` | `worker` |
| **Scheduler** | `langgraph:latest` | `["celery"]` | `["-A", "infrastructure.queue.task_queue", "beat", "--loglevel=info"]` | `scheduler` |

### 1.3 代码加载矩阵 (同一镜像内的运行时选择)

| 代码模块 | Gateway | Worker | Scheduler |
|----------|---------|--------|-----------|
| `gateway/` | ✅ (HTTP 服务) | 存在但不加载 | 存在但不加载 |
| `orchestrator/` | 存在但不加载 | ✅ (图执行) | 存在但不加载 |
| `capabilities/` | 存在但不加载 | ✅ (LLM/Tool) | 存在但不加载 |
| `infrastructure/cache/` | ✅ | ✅ | ❌ |
| `infrastructure/db/` | ❌ | ✅ | ❌ |
| `infrastructure/queue/` | ✅ (投递) | ✅ (消费) | ✅ (beat) |
| `infrastructure/storage/` | ✅ (读) | ✅ (读写) | ❌ |
| `common/` | ✅ | ✅ | ✅ |

---

## 2. 文件清单

| 子目录 | 文件 | 角色 |
|--------|------|------|
| docker | `Dockerfile` | **唯一的镜像** — 包含全部代码，角色由 K8s command 区分 |
| k8s | `deployment-gateway.yaml` | Gateway Deployment: `command: python -m gateway.app` |
| k8s | `deployment-worker.yaml` | Worker Deployment: `command: celery ... worker ...` |
| k8s | `deployment-scheduler.yaml` | Scheduler Deployment: `command: celery ... beat ...` |
| k8s | `service-gateway.yaml` | Service: ClusterIP → Gateway Pods |
| k8s | `ingress.yaml` | Ingress: nginx + TLS (cert-manager) |
| k8s | `hpa-gateway.yaml` | HPA: Gateway (CPU 70%) |
| k8s | `hpa-worker.yaml` | HPA + KEDA: Worker (CPU 70% + Queue Depth) |
| k8s | `statefulset-postgres.yaml` | StatefulSet: Postgres 16 (主从) |
| k8s | `statefulset-redis.yaml` | StatefulSet: Redis 7 (集群) |

---

## 3. Docker 规范

### 3.1 单镜像多角色

**仅有一个 Dockerfile**，包含全部模块代码。Gateway / Worker / Scheduler 三个角色共用同一镜像，K8s 中通过 `command`/`args` 覆盖镜像默认的 `CMD`。

### 3.2 多阶段构建

```
Stage 1: builder
  ├── FROM python:3.12-slim
  ├── 安装 Poetry
  ├── COPY pyproject.toml + poetry.lock
  └── poetry install --only main

Stage 2: runtime
  ├── FROM python:3.12-slim
  ├── COPY --from=builder site-packages
  ├── COPY gateway/ orchestrator/ capabilities/ infrastructure/ common/ (全部)
  ├── 创建非 root 用户 (langgraph)
  └── USER langgraph
```

### 3.3 运行模式

镜像默认 `CMD` 启动 Gateway（方便本地/单机模式直接 `docker run`），集群模式下由各 Deployment 的 `command` + `args` 覆盖：

```yaml
# Gateway — 镜像默认 (保留 CMD)
command: ["uvicorn"]
args: ["gateway.app:app", "--host", "0.0.0.0", "--port", "8000"]

# Worker — 覆盖
command: ["celery"]
args: ["-A", "infrastructure.queue.task_queue", "worker", "--loglevel=info", "--concurrency=4"]

# Scheduler — 覆盖
command: ["celery"]
args: ["-A", "infrastructure.queue.task_queue", "beat", "--loglevel=info"]
```

每个 Deployment 通过 `SERVICE_ROLE` 环境变量标识当前角色：`gateway` / `worker` / `scheduler`。

### 3.4 镜像构建

```bash
# 构建唯一镜像
IMAGE_TAG=$(git rev-parse --short HEAD)
docker build -t langgraph-app:${IMAGE_TAG} -f deployments/docker/Dockerfile .

# 推送
docker push registry.example.com/langgraph-app:${IMAGE_TAG}
```

### 3.5 通用约束

| 规则 | 说明 |
|------|------|
| **MUST** 多阶段构建 | 减小最终镜像体积 |
| **MUST** 非 root 用户 | `USER langgraph`，禁止 root 运行 |
| **MUST** `--only main` | 生产镜像不含 dev 依赖 |
| **MUST NOT** `.env` 进镜像 | 凭据通过 K8s Secret → 环境变量注入 |
| **MUST** 固定 Python 版本 | `python:3.12-slim`，不用 `latest` |
| **MUST** Gateway 镜像有 HEALTHCHECK | `curl -f http://localhost:8000/api/v1/health` |

---

## 4. Kubernetes 规范

### 4.1 部署顺序

```bash
# 先构建唯一镜像
docker build -t your-registry/langgraph-app:latest -f deployments/docker/Dockerfile .
docker push your-registry/langgraph-app:latest

# 1. 基础设施 (先于业务)
kubectl apply -f deployments/k8s/statefulset-postgres.yaml
kubectl apply -f deployments/k8s/statefulset-redis.yaml

# 2. 后端 (无外部依赖)
kubectl apply -f deployments/k8s/deployment-worker.yaml
kubectl apply -f deployments/k8s/hpa-worker.yaml

# 3. 定时任务
kubectl apply -f deployments/k8s/deployment-scheduler.yaml

# 4. 前端 (最后暴露)
kubectl apply -f deployments/k8s/deployment-gateway.yaml
kubectl apply -f deployments/k8s/service-gateway.yaml
kubectl apply -f deployments/k8s/hpa-gateway.yaml
kubectl apply -f deployments/k8s/ingress.yaml
```

### 4.2 Deployment 约束

| 参数 | Gateway | Worker | Scheduler |
|------|---------|--------|-----------|
| **镜像** | `langgraph:latest` | `langgraph:latest` | `langgraph:latest` |
| **command** | `["uvicorn"]` | `["celery"]` | `["celery"]` |
| **args** | `["gateway.app:app", ...]` | `["-A", "...", "worker", ...]` | `["-A", "...", "beat", ...]` |
| **SERVICE_ROLE** | `gateway` | `worker` | `scheduler` |
| replicas (min) | 3 | 5 | 1 |
| terminationGracePeriod | 30s | 60s | 10s |
| PodAntiAffinity | preferred | preferred | N/A |

### 4.3 环境变量注入

| 变量 | Gateway | Worker | 通过 K8s Secret |
|------|---------|--------|---------------|
| `POSTGRES_URI` | ❌ | ✅ | ✅ |
| `REDIS_URI` | ✅ | ✅ | ✅ |
| `CELERY_BROKER_URL` | ✅ | ✅ | ✅ |
| `ANTHROPIC_API_KEY` | ❌ | ✅ | ✅ |
| `OPENAI_API_KEY` | ❌ | ✅ | ✅ |
| `LANGSMITH_API_KEY` | ❌ | ✅ | ✅ |
| `S3_*` | ✅ (只读) | ✅ (读写) | ✅ |

### 4.4 Ingress 约束

| 参数 | 值 | 说明 |
|------|-----|------|
| ingressClassName | nginx | 使用 nginx ingress controller |
| proxy-body-size | 10m | 请求体最大 10MB |
| proxy-read-timeout | 300s | SSE 长连接 5 分钟超时 |
| tls | cert-manager | 自动 TLS 证书管理 |

---

## 5. 弹性伸缩

### 5.1 伸缩策略对比

| 参数 | Gateway | Worker |
|------|---------|--------|
| **HPA: CPU** | > 70%, 3~10 Pods | > 70%, 3~50 Pods |
| **HPA: Memory** | > 80%, 3~10 Pods | > 80%, 3~50 Pods |
| **KEDA: Queue** | ❌ 不适用 | `celery_queue_length > 10`, 3~50 Pods |
| scaleDown 冷却 | 300s | 300s |
| scaleUp 冷却 | 60s | 60s |

### 5.2 KEDA 配置 (Worker)

```yaml
# 需额外安装 KEDA: https://keda.sh
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: langgraph-worker-scaler
spec:
  scaleTargetRef:
    name: langgraph-worker
  minReplicaCount: 3
  maxReplicaCount: 50
  triggers:
    - type: redis
      metadata:
        address: redis:6379
        listName: langgraph_tasks
        listLength: "10"
```

---

## 6. 健康检查

### 6.1 Gateway 探针

```yaml
livenessProbe:
  httpGet:
    path: /api/v1/health
    port: 8000
readinessProbe:
  httpGet:
    path: /api/v1/ready     # 验证 Redis 连通性 (Gateway 不连 Postgres)
    port: 8000
```

### 6.2 Worker 探针

```yaml
# Worker 没有 HTTP 端口，使用命令探针
livenessProbe:
  exec:
    command:
      - python
      - -c
      - "from infrastructure.cache.redis import check_redis; import asyncio; asyncio.run(check_redis())"
  initialDelaySeconds: 30
  periodSeconds: 15
```

### 6.3 基础设施探针

| 组件 | livenessProbe | readinessProbe |
|------|-------------|---------------|
| Postgres | `pg_isready -U langgraph` | `pg_isready -U langgraph` |
| Redis | `redis-cli ping` | `redis-cli ping` |

---

## 7. 密钥管理

### 7.1 Secret 清单

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: langgraph-secrets
type: Opaque
stringData:
  postgres-uri: "postgresql://langgraph:pass@postgres:5432/langgraph"
  postgres-user: "langgraph"
  postgres-password: "<password>"
  redis-uri: "redis://redis:6379/0"
  celery-broker-url: "redis://redis:6379/1"
  s3-endpoint: "http://minio:9000"
  s3-access-key: "minioadmin"
  s3-bucket: "langgraph-data"
  s3-secret-key: "<secret>"
  anthropic-api-key: "sk-ant-..."
  openai-api-key: "sk-..."
  langsmith-api-key: "lsv2_..."
  langsmith-project: "langgraph-cluster"
```

### 7.2 约束

| 规则 | 说明 |
|------|------|
| **MUST** 使用 K8s Secret | 凭据不写入 Deployment YAML |
| **MUST** 通过 `secretKeyRef` 注入 | 环境变量从 Secret 引用 |
| **MUST** Gateway/Worker 共用同一 Secret | 密码统一管理 |
| **MUST NOT** Secret 进 Git | `.gitignore` 忽略，或使用 Sealed Secrets |
| **MUST NOT** 在 Pod log 中打印 | 应用日志已配置自动脱敏 |

---

## 8. 运维流程

### 8.1 发布流程

```
1. 构建唯一镜像 (带 git hash tag)
   docker build -t langgraph-app:${TAG} -f deployments/docker/Dockerfile .
2. 推送到镜像仓库
   docker push registry.example.com/langgraph-app:${TAG}
3. 先滚动更新 Worker (不中断服务)
   kubectl set image deployment/langgraph-worker *=registry.example.com/langgraph-app:${TAG}
4. 再滚动更新 Gateway
   kubectl set image deployment/langgraph-gateway *=registry.example.com/langgraph-app:${TAG}
5. 监控 HPA、KEDA、错误率
6. 确认健康后标记发布完成
```

### 8.2 回滚流程

```bash
# Gateway 回滚
kubectl rollout undo deployment/langgraph-gateway

# Worker 回滚
kubectl rollout undo deployment/langgraph-worker

# 回滚到指定版本
kubectl rollout undo deployment/langgraph-worker --to-revision=3
```

### 8.3 数据库迁移

```bash
# 迁移在独立 Job 中执行，不在应用 Pod 启动时
# Worker 启动前必须完成迁移
kubectl create job --from=cronjob/db-migrate migrate-$(date +%s)
kubectl wait --for=condition=complete job/migrate-*
```

**约束**: 数据库迁移**绝对不允许**在应用 Pod 启动时自动执行。

### 8.4 监控告警建议

| 告警 | 条件 | 级别 |
|------|------|------|
| Pod 重启频繁 | 5 分钟内重启 > 3 次 | Critical |
| 就绪检查失败 | 持续 > 2 分钟 | Warning |
| HPA 触及上限 | replicas = maxReplicas 持续 > 10 分钟 | Warning |
| **队列堆积** | `langgraph_queue_length > 100` 持续 > 5 分钟 | Critical |
| **Worker 全部繁忙** | `langgraph_worker_busy > worker_count * 0.9` | Warning |
| **PubSub 延迟** | `langgraph_pubsub_latency_seconds > 1s` | Warning |
| 5xx 错误率 | > 5% (5 分钟窗口) | Critical |
| Token 消耗异常 | 小时消耗 > 预算的 80% | Warning |
| **Checkpoint 恢复** | `langgraph_checkpoint_recovery_total` 增长过快 | Warning |
