"""
页面路由
-------
Jinja2 模板渲染和静态文件服务。
"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader

from gateway.middleware.auth import request_context

router = APIRouter(tags=["Pages"])

_TPL_DIR = str(Path(__file__).parent.parent / "templates")

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

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    ctx = request_context.get()
    return _render("pages/index.html", {
        "request": request,
        "trace_id": ctx.get("trace_id", "-"),
        "user_id": ctx.get("user_id", "anonymous"),
        "workflows": [],
    })


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    ctx = request_context.get()
    from capabilities.models.factory import ModelFactory
    factory = ModelFactory()
    default_model_name = factory._config.get("default_llm", "")

    # 解析 default_model 的 provider key，生成 "provider::model" 格式的 value
    default_provider = factory.provider_for("llm", default_model_name) if default_model_name else None
    default_model = f"{default_provider}::{default_model_name}" if default_provider and default_model_name else default_model_name

    # 按 provider 分组，下拉框用 <optgroup> 展示
    model_groups: list[dict] = _build_model_groups(factory)

    return _render("pages/chat.html", {
        "request": request,
        "trace_id": ctx.get("trace_id", "-"),
        "user_id": ctx.get("user_id", "anonymous"),
        "model_groups": model_groups,
        "default_model": default_model,
    })


def _build_model_groups(factory) -> list[dict]:
    """按 provider 分组，返回 [{label, models: [{name, display, base_url}]}]。"""
    import yaml
    cfg = factory._config
    llm_cfg = cfg.get("llm", {})

    groups = []
    for provider_key, pconf in llm_cfg.items():
        models = pconf.get("models", {})
        if not models:
            continue
        base_url = pconf.get("base_url", "") or ""
        provider_label = pconf.get("provider", provider_key)

        # 可读的 group label
        label_map = {
            "anthropic": "Anthropic (Claude)",
            "openai": "OpenAI (GPT)",
            "custom": "自定义 / vLLM",
            "llama_cpp": f"llama.cpp ({base_url})" if base_url else "llama.cpp",
        }
        label = label_map.get(provider_key, provider_key)

        groups.append({
            "label": label,
            "models": [
                {"name": f"{provider_key}::{name}", "display": name}
                for name in sorted(models.keys())
            ],
        })

    return groups


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


@router.get("/dictionary", response_class=HTMLResponse)
async def dictionary_page(request: Request):
    ctx = request_context.get()
    return _render("pages/dictionary.html", {
        "request": request,
        "trace_id": ctx.get("trace_id", "-"),
        "user_id": ctx.get("user_id", "anonymous"),
    })


@router.get("/metadata", response_class=HTMLResponse)
async def metadata_page(request: Request):
    ctx = request_context.get()
    return _render("pages/metadata.html", {
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


@router.get("/intelligence", response_class=HTMLResponse)
async def intelligence_page(request: Request):
    ctx = request_context.get()
    return _render("pages/intelligence.html", {
        "request": request,
        "trace_id": ctx.get("trace_id", "-"),
        "user_id": ctx.get("user_id", "anonymous"),
    })
