"""
页面路由
-------
Jinja2 模板渲染和静态文件服务。（模板文件位于 webAPP/templates/）
"""
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


@router.get("/ontology-template", response_class=HTMLResponse)
async def ontology_template_page(request: Request):
    ctx = request_context.get()
    return _render("pages/ontology_template.html", {
        "request": request,
        "trace_id": ctx.get("trace_id", "-"),
        "user_id": ctx.get("user_id", "anonymous"),
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
