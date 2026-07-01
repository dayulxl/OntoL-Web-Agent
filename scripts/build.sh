#!/bin/bash
# ============================================================
# Docker 镜像构建脚本
# ============================================================
set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-langgraph}"
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD 2>/dev/null || echo 'latest')}"
REGISTRY="${REGISTRY:-}"

FULL_IMAGE="${REGISTRY:+${REGISTRY}/}${IMAGE_NAME}:${IMAGE_TAG}"

echo "==> Building Docker image: ${FULL_IMAGE}"
docker build \
  -t "${FULL_IMAGE}" \
  -t "${IMAGE_NAME}:latest" \
  -f deployments/docker/Dockerfile \
  .

echo "==> Image built successfully: ${FULL_IMAGE}"

# Push if registry is configured
if [ -n "${REGISTRY:-}" ]; then
  echo "==> Pushing to registry: ${REGISTRY}"
  docker push "${FULL_IMAGE}"
  echo "==> Push completed"
fi
