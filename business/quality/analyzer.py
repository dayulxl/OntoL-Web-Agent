"""
数据质量分析服务
--------------
对 SQLite (本体模型) 和 Memgraph (知识图谱) 执行多维数据质量评估。
输出结构化指标供前端报表使用。
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from common.utils.logger import get_logger

logger = get_logger(__name__)

DB_PATH = Path("infrastructure/db/ontol.db")

# ── 质量维度 ──

@dataclass
class DimensionScore:
    """单个质量维度的评分"""
    name: str           # 维度名称
    label: str          # 中文标签
    score: float        # 0~100
    status: str         # "good" | "warning" | "bad"
    detail: str         # 一句话说明
    issues: list[dict] = field(default_factory=list)


@dataclass
class QualityReport:
    """完整质量报告"""
    overall_score: float
    dimensions: list[DimensionScore]
    summary: str
    table_counts: dict[str, int]
    chart_data: dict[str, Any]      # FrappeCharts 格式
    detail_tables: dict[str, list[dict]]  # 各维度详细数据表
    generated_at: str


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# ═══════════════════════════════════════════════════════════════════════════
# 各维度独立分析
# ═══════════════════════════════════════════════════════════════════════════

def _completeness(conn: sqlite3.Connection) -> DimensionScore:
    """完整性: 必填字段缺失率、模型属性覆盖率"""
    total_models = conn.execute(
        "SELECT COUNT(*) as c FROM ontol_model WHERE delete_flag='0'"
    ).fetchone()["c"]

    # 有属性的模型数
    models_with_attrs = conn.execute("""
        SELECT COUNT(DISTINCT m.id) as c
        FROM ontol_model m
        INNER JOIN ontol_model_attr a ON a.ontol_model_id = m.id AND a.delete_flag='0'
        WHERE m.delete_flag='0'
    """).fetchone()["c"]

    # 必填字段缺少默认值
    missing_defaults = conn.execute(
        "SELECT COUNT(*) as c FROM ontol_model_attr "
        "WHERE attr_required='1' AND (attr_default_value IS NULL OR attr_default_value='') "
        "AND delete_flag='0'"
    ).fetchone()["c"]

    attr_rate = (models_with_attrs / total_models * 100) if total_models else 0
    score = max(0, 100 - (total_models - models_with_attrs) * 5 - missing_defaults * 2)

    if score >= 80:
        status = "good"
    elif score >= 50:
        status = "warning"
    else:
        status = "bad"

    issues = []
    if total_models - models_with_attrs > 0:
        issues.append({
            "level": "warning",
            "msg": f"{total_models - models_with_attrs} 个模型未定义任何属性字段",
            "count": total_models - models_with_attrs,
        })
    if missing_defaults > 0:
        issues.append({
            "level": "info",
            "msg": f"{missing_defaults} 个必填字段缺少默认值",
            "count": missing_defaults,
        })

    return DimensionScore(
        name="completeness",
        label="完整性",
        score=round(min(100, max(0, score))),
        status=status,
        detail=f"属性覆盖率 {attr_rate:.0f}%（{models_with_attrs}/{total_models}）",
        issues=issues,
    )


def _consistency(conn: sqlite3.Connection) -> DimensionScore:
    """一致性: 外键引用有效性、孤儿记录"""
    # 没有提示词的场景
    orphan_scenes = conn.execute("""
        SELECT s.id, s.name FROM ontol_model_scene s
        LEFT JOIN ontol_scene_prompt p ON s.id = p.scene_id
        WHERE p.id IS NULL AND s.delete_flag='0'
    """).fetchall()

    # 属性引用了不存在的模型
    orphan_attrs = conn.execute("""
        SELECT a.id, a.code, a.ontol_model_id
        FROM ontol_model_attr a
        LEFT JOIN ontol_model m ON a.ontol_model_id = m.id AND m.delete_flag='0'
        WHERE m.id IS NULL AND a.delete_flag='0'
    """).fetchall()

    # 提示词引用了不存在的场景
    orphan_prompts = conn.execute("""
        SELECT p.id, p.name, p.scene_id
        FROM ontol_scene_prompt p
        LEFT JOIN ontol_model_scene s ON p.scene_id = s.id AND s.delete_flag='0'
        WHERE s.id IS NULL AND p.delete_flag='0'
    """).fetchall()

    total_issues = len(orphan_scenes) + len(orphan_attrs) + len(orphan_prompts)
    if total_issues == 0:
        score, status = 100.0, "good"
    elif total_issues <= 3:
        score, status = 70.0, "warning"
    else:
        score, status = 40.0, "bad"

    issues = []
    for s in orphan_scenes:
        issues.append({
            "level": "warning",
            "msg": f"场景 '{s['name']}' 无关联提示词",
            "table": "ontol_model_scene",
            "id": s["id"],
        })
    for a in orphan_attrs:
        issues.append({
            "level": "error",
            "msg": f"属性 '{a['code']}' 引用不存在的模型 {a['ontol_model_id']}",
            "table": "ontol_model_attr",
            "id": a["id"],
        })
    for p in orphan_prompts:
        issues.append({
            "level": "error",
            "msg": f"提示词 '{p['name']}' 引用不存在的场景 {p['scene_id']}",
            "table": "ontol_scene_prompt",
            "id": p["id"],
        })

    return DimensionScore(
        name="consistency",
        label="一致性",
        score=score,
        status=status,
        detail=f"{total_issues} 个孤立引用" if total_issues else "全部关联有效",
        issues=issues,
    )


def _freshness(conn: sqlite3.Connection) -> DimensionScore:
    """时效性: 各表最近更新时间、过期数据比例"""
    now = datetime.now()
    tables = [
        "ontol_model", "ontol_model_attr", "ontol_model_scene",
        "ontol_scene_prompt", "ontol_cope_version", "ontol_data_his",
        "ontol_llm_config", "ontol_llm_type_config",
    ]

    stale_count = 0
    fresh_count = 0
    table_details = []

    for tbl in tables:
        # 检查表有哪些时间字段（兼容不同表结构）
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info(\"{tbl}\")").fetchall()}
        has_update = "update_time" in cols
        has_create = "create_time" in cols
        has_delete = "delete_flag" in cols
        if not has_create:
            continue  # 没有时间字段的表跳过
        time_expr = (
            f"CASE WHEN update_time IS NOT NULL AND update_time != '' THEN update_time "
            f"ELSE create_time END"
        ) if has_update else "create_time"
        where_cl = "WHERE delete_flag='0'" if has_delete else ""
        rows = conn.execute(
            f"SELECT MAX({time_expr}) as last_ts FROM \"{tbl}\" {where_cl}"
        ).fetchone()
        last_ts = rows["last_ts"] if rows else None
        if last_ts:
            try:
                last_dt = datetime.strptime(last_ts[:19], "%Y-%m-%d %H:%M:%S")
                age_days = (now - last_dt).days
                if age_days > 30:
                    stale_count += 1
                else:
                    fresh_count += 1
                table_details.append({
                    "table": tbl,
                    "last_update": last_ts[:19],
                    "age_days": age_days,
                })
            except ValueError:
                table_details.append({"table": tbl, "last_update": last_ts, "age_days": -1})

    total = stale_count + fresh_count
    score = (fresh_count / total * 100) if total else 100
    if score >= 80:
        status = "good"
    elif score >= 50:
        status = "warning"
    else:
        status = "bad"

    issues = []
    stale_tables = [t for t in table_details if t["age_days"] > 30]
    if stale_tables:
        issues.append({
            "level": "warning",
            "msg": f"{len(stale_tables)} 张表超过 30 天未更新",
            "tables": [t["table"] for t in stale_tables],
        })

    return DimensionScore(
        name="freshness",
        label="时效性",
        score=round(score),
        status=status,
        detail=f"{fresh_count}/{total} 表在 30 天内有更新",
        issues=issues,
    )


def _uniqueness(conn: sqlite3.Connection) -> DimensionScore:
    """唯一性: 重复名称/编码检测"""
    # 模型重名
    dup_models = conn.execute("""
        SELECT name, COUNT(*) as cnt FROM ontol_model
        WHERE delete_flag='0' GROUP BY name HAVING cnt > 1
    """).fetchall()

    # 场景重名
    dup_scenes = conn.execute("""
        SELECT name, COUNT(*) as cnt FROM ontol_model_scene
        WHERE delete_flag='0' GROUP BY name HAVING cnt > 1
    """).fetchall()

    # 属性 code 同模型内重复
    dup_attrs = conn.execute("""
        SELECT ontol_model_id, code, COUNT(*) as cnt
        FROM ontol_model_attr WHERE delete_flag='0'
        GROUP BY ontol_model_id, code HAVING cnt > 1
    """).fetchall()

    total_dups = len(dup_models) + len(dup_scenes) + len(dup_attrs)
    if total_dups == 0:
        score, status = 100.0, "good"
    elif total_dups <= 3:
        score, status = 75.0, "warning"
    else:
        score, status = 40.0, "bad"

    issues = []
    for m in dup_models:
        issues.append({
            "level": "warning",
            "msg": f"模型名称 '{m['name']}' 重复 {m['cnt']} 次",
            "table": "ontol_model",
        })
    for s in dup_scenes:
        issues.append({
            "level": "warning",
            "msg": f"场景名称 '{s['name']}' 重复 {s['cnt']} 次",
            "table": "ontol_model_scene",
        })
    for a in dup_attrs:
        issues.append({
            "level": "error",
            "msg": f"模型 {a['ontol_model_id']} 中 code '{a['code']}' 重复 {a['cnt']} 次",
            "table": "ontol_model_attr",
            "model_id": a["ontol_model_id"],
            "code": a["code"],
        })

    return DimensionScore(
        name="uniqueness",
        label="唯一性",
        score=score,
        status=status,
        detail="无重复记录" if total_dups == 0 else f"{total_dups} 处重复",
        issues=issues,
    )


def _coverage(conn: sqlite3.Connection) -> DimensionScore:
    """覆盖率: 系统预设完整性、各子系统数据填充度"""
    metrics = {}

    # 模型统计
    model_stats = conn.execute("""
        SELECT
            SUM(CASE WHEN ontol_type='01' THEN 1 ELSE 0 END) as entity_count,
            SUM(CASE WHEN ontol_type='02' THEN 1 ELSE 0 END) as relation_count,
            SUM(CASE WHEN ontol_model_is_system='1' THEN 1 ELSE 0 END) as system_count,
            COUNT(*) as total
        FROM ontol_model WHERE delete_flag='0'
    """).fetchone()
    metrics["models"] = dict(model_stats)

    # 属性: system vs custom
    attr_stats = conn.execute("""
        SELECT
            SUM(CASE WHEN attr_is_system='1' THEN 1 ELSE 0 END) as system_attrs,
            SUM(CASE WHEN attr_is_system!='1' OR attr_is_system IS NULL THEN 1 ELSE 0 END) as custom_attrs,
            COUNT(*) as total
        FROM ontol_model_attr WHERE delete_flag='0'
    """).fetchone()
    metrics["attrs"] = dict(attr_stats)

    # 场景
    scene_count = conn.execute(
        "SELECT COUNT(*) as c FROM ontol_model_scene WHERE delete_flag='0'"
    ).fetchone()["c"]
    metrics["scenes"] = scene_count

    # 提示词
    prompt_count = conn.execute(
        "SELECT COUNT(*) as c FROM ontol_scene_prompt WHERE delete_flag='0'"
    ).fetchone()["c"]
    metrics["prompts"] = prompt_count

    # LLM 配置
    llm_count = conn.execute(
        "SELECT COUNT(*) as c FROM ontol_llm_config WHERE delete_flag='0'"
    ).fetchone()["c"]
    metrics["llm_configs"] = llm_count

    # 对话-场景绑定
    chat_bindings = conn.execute(
        "SELECT COUNT(*) as c FROM ontol_char_scene_relation WHERE delete_flag='0'"
    ).fetchone()["c"]
    metrics["chat_bindings"] = chat_bindings

    # 数据源
    ds_count = conn.execute(
        "SELECT COUNT(*) as c FROM ontol_datasource WHERE delete_flag='0' AND status != 0"
    ).fetchone()["c"]
    metrics["active_datasources"] = ds_count

    # 计算得分: 每个子系统有数据即得分
    checks = [
        (metrics["models"]["total"] > 0, "模型定义"),
        (metrics["attrs"]["total"] > 0, "属性字段"),
        (metrics["scenes"] > 0, "推演场景"),
        (metrics["prompts"] > 0, "场景提示词"),
        (metrics["llm_configs"] > 0, "LLM 配置"),
        (metrics["chat_bindings"] > 0, "对话-场景绑定"),
        (metrics["active_datasources"] > 0, "数据源配置"),
    ]
    passed = sum(1 for ok, _ in checks if ok)
    score = (passed / len(checks)) * 100

    if score >= 80:
        status = "good"
    elif score >= 50:
        status = "warning"
    else:
        status = "bad"

    issues = []
    for ok, label in checks:
        if not ok:
            issues.append({
                "level": "info",
                "msg": f"{label} 尚未配置",
            })

    return DimensionScore(
        name="coverage",
        label="覆盖率",
        score=round(score),
        status=status,
        detail=f"{passed}/{len(checks)} 子系统有数据",
        issues=issues,
    )


# ═══════════════════════════════════════════════════════════════════════════
# 综合分析
# ═══════════════════════════════════════════════════════════════════════════

def analyze_all() -> QualityReport:
    """执行全维度数据质量分析，返回结构化报告。"""
    t0 = time.time()
    conn = _get_conn()
    try:
        dims = [
            _completeness(conn),
            _consistency(conn),
            _uniqueness(conn),
            _freshness(conn),
            _coverage(conn),
        ]

        overall = sum(d.score for d in dims) / len(dims)
        if overall >= 80:
            overall_status = "优秀"
        elif overall >= 60:
            overall_status = "良好"
        elif overall >= 40:
            overall_status = "需改进"
        else:
            overall_status = "较差"

        total_issues = sum(len(d.issues) for d in dims)
        summary = f"综合评分 {overall_status}，{len(dims)} 个维度评估完成，发现 {total_issues} 项问题"

        # ── 构建图表数据 ──
        chart_data = _build_chart_data(dims, conn)

        # ── 表行数统计 ──
        table_counts = _get_table_counts(conn)

        # ── 详情数据表 ──
        detail_tables = _build_detail_tables(conn)

        elapsed = time.time() - t0
        logger.info("Data quality analysis completed", extra={
            "overall_score": round(overall, 1),
            "dimensions": len(dims),
            "issues": total_issues,
            "elapsed_ms": round(elapsed * 1000),
        })

        return QualityReport(
            overall_score=round(overall, 1),
            dimensions=dims,
            summary=summary,
            table_counts=table_counts,
            chart_data=chart_data,
            detail_tables=detail_tables,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
    finally:
        conn.close()


def _get_table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """获取各业务表的记录数。"""
    tables = [
        "ontol_model", "ontol_model_attr", "ontol_model_scene",
        "ontol_scene_prompt", "ontol_cope_version", "ontol_data_his",
        "ontol_llm_config", "ontol_llm_type_config",
        "ontol_datasource", "ontol_datasource_type",
        "ontol_char_scene_relation", "ontol_node_scene_relation",
        "ontol_scene_dictionary", "ontol_dictionary_type",
    ]
    counts = {}
    for tbl in tables:
        c = conn.execute(
            f"SELECT COUNT(*) as c FROM \"{tbl}\" WHERE delete_flag='0'"
        ).fetchone()["c"]
        label = tbl.replace("ontol_", "")
        counts[label] = c
    return counts


def _build_chart_data(dims: list[DimensionScore],
                      conn: sqlite3.Connection) -> dict[str, Any]:
    """构建 FrappeCharts 所需的图表数据。"""

    # ── 雷达图: 各维度评分 ──
    radar = {
        "labels": [d.label for d in dims],
        "datasets": [{
            "name": "数据质量评分",
            "values": [d.score for d in dims],
        }],
    }

    # ── 模型类型分布 (饼图/环形图) ──
    type_dist = conn.execute("""
        SELECT ontol_type, COUNT(*) as cnt
        FROM ontol_model WHERE delete_flag='0'
        GROUP BY ontol_type
    """).fetchall()
    type_labels = {
        "01": "实体类型",
        "02": "关系类型",
    }
    pie_labels = [type_labels.get(r["ontol_type"], r["ontol_type"]) for r in type_dist]
    pie_values = [r["cnt"] for r in type_dist]
    pie = {
        "labels": pie_labels,
        "datasets": [{"name": "模型分布", "values": pie_values}],
    }

    # ── 问题分布 (柱状图) ──
    bar = {
        "labels": [d.label for d in dims],
        "datasets": [{
            "name": "问题数",
            "values": [len(d.issues) for d in dims],
        }],
    }

    # ── 趋势数据: 数据历史按月分布 ──
    trend = conn.execute("""
        SELECT substr(create_time, 1, 7) as month, COUNT(*) as cnt
        FROM ontol_data_his WHERE delete_flag='0'
        GROUP BY month ORDER BY month
    """).fetchall()
    trend_data = {
        "labels": [r["month"] for r in trend],
        "datasets": [{
            "name": "变更次数",
            "values": [r["cnt"] for r in trend],
        }],
    }

    return {
        "radar": radar,
        "pie": pie,
        "bar": bar,
        "trend": trend_data,
    }


def _build_detail_tables(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    """构建各维度的详细数据表，供前端表格展示。"""

    # ── 模型属性概览 ──
    model_attrs = conn.execute("""
        SELECT m.id, m.name, m.ontol_type, m.ontol_model_is_system,
               COUNT(a.id) as attr_count,
               SUM(CASE WHEN a.attr_is_system='1' THEN 1 ELSE 0 END) as system_attrs,
               SUM(CASE WHEN a.attr_is_system!='1' OR a.attr_is_system IS NULL THEN 1 ELSE 0 END) as custom_attrs
        FROM ontol_model m
        LEFT JOIN ontol_model_attr a ON a.ontol_model_id = m.id AND a.delete_flag='0'
        WHERE m.delete_flag='0'
        GROUP BY m.id
        ORDER BY attr_count ASC, m.name
    """).fetchall()
    model_detail = []
    for r in model_attrs:
        model_detail.append({
            "id": r["id"],
            "name": r["name"],
            "type": "实体" if r["ontol_type"] == "01" else "关系" if r["ontol_type"] == "02" else r["ontol_type"],
            "is_system": "系统" if r["ontol_model_is_system"] == "1" else "自定义",
            "attr_count": r["attr_count"],
            "system_attrs": r["system_attrs"] or 0,
            "custom_attrs": r["custom_attrs"] or 0,
        })

    # ── 缺少属性的模型 ──
    missing_attr_models = [m for m in model_detail if m["attr_count"] == 0]

    # ── 最近数据变更 ──
    recent_changes = conn.execute("""
        SELECT id, node_id, context, create_time
        FROM ontol_data_his WHERE delete_flag='0'
        ORDER BY create_time DESC LIMIT 20
    """).fetchall()
    changes_detail = []
    for r in recent_changes:
        changes_detail.append({
            "id": r["id"],
            "node_id": r["node_id"],
            "context": (r["context"] or "")[:80],
            "create_time": r["create_time"][:19] if r["create_time"] else "",
        })

    # ── 场景提示词覆盖率 ──
    scene_prompts = conn.execute("""
        SELECT s.id, s.name as scene_name, s.scene_is_system,
               COUNT(p.id) as prompt_count
        FROM ontol_model_scene s
        LEFT JOIN ontol_scene_prompt p ON s.id = p.scene_id AND p.delete_flag='0'
        WHERE s.delete_flag='0'
        GROUP BY s.id
        ORDER BY prompt_count ASC
    """).fetchall()
    scene_detail = []
    for r in scene_prompts:
        scene_detail.append({
            "id": r["id"],
            "name": r["scene_name"],
            "is_system": "系统" if r["scene_is_system"] == "1" else "自定义",
            "prompt_count": r["prompt_count"],
        })

    return {
        "model_attrs": model_detail,
        "missing_attr_models": missing_attr_models,
        "recent_changes": changes_detail,
        "scene_prompts": scene_detail,
    }
