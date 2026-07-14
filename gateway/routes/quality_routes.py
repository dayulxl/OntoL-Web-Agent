"""
数据质量分析 API
----------------
GET /api/v1/quality/report → 全维度数据质量报告
"""
from fastapi import APIRouter

from business.quality.analyzer import analyze_all

router = APIRouter(tags=["Data Quality"])


@router.get("/api/v1/quality/report")
async def get_quality_report():
    """获取数据质量全维度分析报告。"""
    report = analyze_all()
    return {
        "code": 200,
        "data": {
            "overall_score": report.overall_score,
            "dimensions": [
                {
                    "name": d.name,
                    "label": d.label,
                    "score": d.score,
                    "status": d.status,
                    "detail": d.detail,
                    "issues": d.issues,
                }
                for d in report.dimensions
            ],
            "summary": report.summary,
            "table_counts": report.table_counts,
            "chart_data": report.chart_data,
            "detail_tables": report.detail_tables,
            "generated_at": report.generated_at,
        },
    }
