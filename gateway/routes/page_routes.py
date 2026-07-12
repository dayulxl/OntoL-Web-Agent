"""
页面路由
-------
Jinja2 模板渲染和静态文件服务。（模板文件位于 webAPP/templates/）
"""
import json as _json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader

from gateway.middleware.auth import request_context

router = APIRouter(tags=["Pages"])

_TPL_DIR = str(Path(__file__).parent.parent.parent / "webAPP" / "templates")

_env = Environment(loader=FileSystemLoader(_TPL_DIR), autoescape=True)

# url_for 作为全局函数注入 (在模板中用 {{ url_for('static', path='...') }})
def _url_for_wrapper(endpoint: str, **kwargs):
    return f"/{endpoint}?{'&'.join(f'{k}={v}' for k,v in kwargs.items())}"
_env.globals["url_for"] = _url_for_wrapper


# ==== 渲染 ====

def _render(template_name: str, context: dict) -> HTMLResponse:
    """渲染 Jinja2 模板。"""
    tpl = _env.get_template(template_name)
    request = context.get("request")
    if request and hasattr(request, "url_for"):
        context["url_for"] = request.url_for
    return HTMLResponse(tpl.render(**context))


# =========================================================================
# 路由
# =========================================================================

@router.get("/")
async def dashboard():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/chat", status_code=302)


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    ctx = request_context.get()

    model_groups: list[dict] = await _build_model_groups_from_db()

    # 默认选中第一个模型
    default_model = ""
    for g in model_groups:
        if g["models"]:
            default_model = g["models"][0]["id"]
            break

    return _render("pages/chat.html", {
        "request": request,
        "trace_id": ctx.get("trace_id", "-"),
        "user_id": ctx.get("user_id", "anonymous"),
        "model_groups": model_groups,
        "default_model": default_model,
    })


async def _build_model_groups_from_db() -> list[dict]:
    """从 ontol_llm_type_config + ontol_llm_config 表构建模型分组。"""
    import sqlite3
    from pathlib import Path

    db_path = Path("infrastructure/db/ontol.db")
    if not db_path.exists():
        return []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    types_rows = conn.execute(
        "SELECT * FROM ontol_llm_type_config WHERE delete_flag='0' ORDER BY create_time"
    ).fetchall()

    configs_rows = conn.execute(
        "SELECT * FROM ontol_llm_config WHERE delete_flag='0' ORDER BY create_time"
    ).fetchall()
    conn.close()

    # 按 type_config_id 分组
    type_map = {t["id"]: {"label": t["name"], "models": []} for t in types_rows}
    for c in configs_rows:
        tid = c["llm_type_config_id"]
        if tid in type_map:
            type_map[tid]["models"].append({
                "id": c["id"],
                "name": c["name"],
            })

    return [v for v in type_map.values() if v["models"]]


@router.get("/workflow/{name}", response_class=HTMLResponse)
async def workflow_detail(request: Request, name: str):
    ctx = request_context.get()
    return _render("pages/workflow.html", {
        "request": request,
        "trace_id": ctx.get("trace_id", "-"),
        "user_id": ctx.get("user_id", "anonymous"),
        "workflow": {"name": name, "status": "active", "node_count": 0},
    })


def _build_ontology_tree_for_view() -> list:
    """从 SQLite ontol_model / ontol_model_attr 表加载本体类型，输出 js-treeview 格式。"""
    import sqlite3
    from pathlib import Path as _Path

    db_path = _Path("infrastructure/db/ontol.db")
    if not db_path.exists():
        return []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        models = conn.execute(
            "SELECT id, name, ontol_parent_id AS parent_id, ontol_model_type AS type_code, "
            "ontol_model_desc AS desc FROM ontol_model WHERE delete_flag='0' ORDER BY id"
        ).fetchall()
        attrs = conn.execute(
            "SELECT ontol_model_id, code FROM ontol_model_attr "
            "WHERE delete_flag='0'"
        ).fetchall()
    finally:
        conn.close()

    if not models:
        return []

    # 统计每个模型的字段数
    attr_counts: dict[str, int] = {}
    for a in attrs:
        mid = a["ontol_model_id"]
        attr_counts[mid] = attr_counts.get(mid, 0) + 1

    # 构建 types dict
    types: dict[str, dict] = {}
    for m in models:
        types[m["id"]] = {
            "id": m["id"],
            "parent_id": m["parent_id"],
            "name": m["name"],
            "type_code": m["type_code"] or "",
            "desc": (m["desc"] or "").strip(),
            "field_count": attr_counts.get(m["id"], 0),
        }

    def build_node(type_id: str) -> dict:
        t = types[type_id]
        node = {
            "name": _fmt_node_name(t),
            "id": t["id"],
            "typeCode": t["type_code"],
            "fieldCount": t["field_count"],
            "desc": t["desc"],
            "children": [],
        }
        # 找直接子节点
        child_ids = sorted(
            [cid for cid, ct in types.items()
             if ct.get("parent_id") == type_id and cid != type_id],
            key=lambda x: types[x]["name"]
        )
        for cid in child_ids:
            node["children"].append(build_node(cid))
        if not node["children"]:
            node.pop("children")  # leaf → select 事件触发
        return node

    def _fmt_node_name(t: dict) -> str:
        fc = t["field_count"]
        parts = [t["id"]]
        if t["name"] and t["name"] != t["id"]:
            parts.append(f"({t['name']})")
        if fc > 0:
            parts.append(f"[{fc}字段]")
        return " ".join(parts)

    # 找根节点
    roots = []
    for tid, t in types.items():
        parent_id = t.get("parent_id")
        if not parent_id or parent_id not in types or parent_id == tid:
            node = build_node(tid)
            node["expanded"] = True
            roots.append(node)

    return roots


@router.get("/ontology-template", response_class=HTMLResponse)
async def ontology_template_page(request: Request):
    ctx = request_context.get()
    tree = _build_ontology_tree_for_view()
    ontology_tree_json = _json.dumps(tree, ensure_ascii=False, default=str)
    return _render("pages/ontology_template.html", {
        "request": request,
        "trace_id": ctx.get("trace_id", "-"),
        "user_id": ctx.get("user_id", "anonymous"),
        "ontology_tree_json": ontology_tree_json,
    })


@router.get("/ontology", response_class=HTMLResponse)
async def ontology_page(request: Request):
    ctx = request_context.get()
    return _render("pages/ontology.html", {
        "request": request,
        "trace_id": ctx.get("trace_id", "-"),
        "user_id": ctx.get("user_id", "anonymous"),
    })


@router.get("/sandbox", response_class=HTMLResponse)
async def sandbox_page(request: Request):
    ctx = request_context.get()
    return _render("pages/sandbox.html", {
        "request": request,
        "trace_id": ctx.get("trace_id", "-"),
        "user_id": ctx.get("user_id", "anonymous"),
    })


@router.get("/sandbox-wargame", response_class=HTMLResponse)
async def sandbox_wargame_page(request: Request):
    ctx = request_context.get()
    return _render("pages/sandbox_wargame.html", {
        "request": request,
        "trace_id": ctx.get("trace_id", "-"),
        "user_id": ctx.get("user_id", "anonymous"),
    })


@router.get("/upload", response_class=HTMLResponse)
async def upload_page(request: Request):
    ctx = request_context.get()
    return _render("pages/upload.html", {
        "request": request,
        "trace_id": ctx.get("trace_id", "-"),
        "user_id": ctx.get("user_id", "anonymous"),
    })


@router.get("/graph", response_class=HTMLResponse)
async def graph_page(request: Request):
    ctx = request_context.get()
    return _render("pages/graph.html", {
        "request": request,
        "trace_id": ctx.get("trace_id", "-"),
        "user_id": ctx.get("user_id", "anonymous"),
    })


@router.get("/reasoner-world", response_class=HTMLResponse)
async def reasoner_world_page(request: Request):
    ctx = request_context.get()
    return _render("pages/reasoner_world.html", {
        "request": request,
        "trace_id": ctx.get("trace_id", "-"),
        "user_id": ctx.get("user_id", "anonymous"),
    })



@router.get("/metadata", response_class=HTMLResponse)
async def metadata_page(request: Request):
    ctx = request_context.get()
    return _render("pages/dictionary.html", {
        "request": request,
        "trace_id": ctx.get("trace_id", "-"),
        "user_id": ctx.get("user_id", "anonymous"),
    })


@router.get("/data-ingestion", response_class=HTMLResponse)
async def data_ingestion_page(request: Request):
    ctx = request_context.get()
    return _render("pages/data_ingestion.html", {
        "request": request,
        "trace_id": ctx.get("trace_id", "-"),
        "user_id": ctx.get("user_id", "anonymous"),
    })


@router.get("/datamanage", response_class=HTMLResponse)
async def datamanage_page(request: Request):
    ctx = request_context.get()
    return _render("pages/datamanage.html", {
        "request": request,
        "trace_id": ctx.get("trace_id", "-"),
        "user_id": ctx.get("user_id", "anonymous"),
    })


@router.get("/intelligence", response_class=HTMLResponse)
async def intelligence_page(request: Request):
    ctx = request_context.get()
    return _render("pages/intelligence.html", {
        "request": request,
        "trace_id": ctx.get("trace_id", "-"),
        "user_id": ctx.get("user_id", "anonymous"),
    })


@router.get("/llm-config", response_class=HTMLResponse)
async def llm_config_page(request: Request):
    ctx = request_context.get()
    return _render("pages/llm_config.html", {
        "request": request,
        "trace_id": ctx.get("trace_id", "-"),
        "user_id": ctx.get("user_id", "anonymous"),
    })


@router.get("/prompt-manager", response_class=HTMLResponse)
async def prompt_manager_page(request: Request):
    ctx = request_context.get()
    return _render("pages/prompt_manager.html", {
        "request": request,
        "trace_id": ctx.get("trace_id", "-"),
        "user_id": ctx.get("user_id", "anonymous"),
    })


@router.get("/function-manager", response_class=HTMLResponse)
async def function_manager_page(request: Request):
    ctx = request_context.get()
    return _render("pages/function_manager.html", {
        "request": request,
        "trace_id": ctx.get("trace_id", "-"),
        "user_id": ctx.get("user_id", "anonymous"),
    })
