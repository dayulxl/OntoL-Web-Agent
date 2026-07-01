#!/bin/bash
# ============================================================
# 数据库迁移脚本
# 使用 Alembic 执行数据库 schema 变更
# ============================================================
set -euo pipefail

ALEMBIC_INI="${ALEMBIC_INI:-alembic.ini}"
ACTION="${1:-upgrade}"
MIGRATION_MSG="${2:-auto migration}"

case "${ACTION}" in
  upgrade)
    echo "==> Running database migrations (upgrade to head)..."
    alembic -c "${ALEMBIC_INI}" upgrade head
    echo "==> Migration completed"
    ;;

  downgrade)
    echo "==> Rolling back last migration..."
    alembic -c "${ALEMBIC_INI}" downgrade -1
    echo "==> Rollback completed"
    ;;

  revision)
    echo "==> Creating new migration: ${MIGRATION_MSG}"
    alembic -c "${ALEMBIC_INI}" revision --autogenerate -m "${MIGRATION_MSG}"
    echo "==> Migration file created"
    ;;

  history)
    echo "==> Migration history:"
    alembic -c "${ALEMBIC_INI}" history
    ;;

  current)
    echo "==> Current migration:"
    alembic -c "${ALEMBIC_INI}" current
    ;;

  *)
    echo "Usage: $0 {upgrade|downgrade|revision|history|current} [migration_message]"
    exit 1
    ;;
esac
