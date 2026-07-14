"""
Chat Agent — 推理管道
=====================
基于 LangGraph ReAct Agent 的多步推理管道：

1. 意图解析 — 拆解用户目标
2. 知识检索 — 图数据库（Memgraph/Neo4j） + SQLite 本体模型 + 推理机
3. 图遍历 — 最多 4 层关系检索
4. 步骤生成 — 动态拆分执行步骤 + 验收标准
5. 自校验 — 最多 3 次重试
6. 方案输出 — 最终计划
"""
import json
import asyncio
from typing import Optional, AsyncIterator

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from common.config.settings import get_settings
from common.utils.logger import get_logger

logger = get_logger(__name__)

# =============================================================================
# System Prompt
# =============================================================================

SYSTEM_PROMPT = """你是一个军事知识图谱推理助手。处理用户问题时，必须按照以下流程执行：

## 本体分类体系

系统预定义了以下本体分类层级（M_ROOT 为根节点）：

| 本体ID | 父级 | 名称 | 编码 | 说明 |
|--------|------|------|------|------|
| M_ROOT | - | 基本本体 | M0 | 通用字段，例如 id、create_time、update_time 等 |
| M_ENTITY | M_ROOT | 实体 | M1 | 兵力、装备、设施等实体节点 |
| M_BEHAVIOR | M_ROOT | 行为 | M2 | 攻击、机动、防御、侦察等行为动作 |
| M_RULE | M_ROOT | 规则 | M3 | 作战规则、交战规则、触发条件 |
| M_SCENE | M_ROOT | 场景 | M4 | 战场环境、时空背景 |
| M_AGENT | M_ROOT | 主体 | M5 | 指挥单元、决策主体 |
| M_EXCEPTION | M_ROOT | 异常补偿 | M6 | 异常处理、故障恢复 |
| M_QUALITY | M_ROOT | 质量约束 | M7 | 精度、时效性、可靠性约束 |
| M_AGGR | M_ROOT | 聚合本体 | M8 | 编组、集群、聚合关系 |
| M_EVENT | M_ROOT | 事件 | ME | 战场事件、态势变化 |

## 执行流程（严格按顺序）

### 第1步：本体查询
- 调用 get_ontology_tree 获取完整的本体层级结构
- 根据用户问题的语义，匹配对应的本体分类（从上述体系中查找最相关的分类）

### 第2步：分类匹配与行为查找
- 调用 get_model_detail 查看匹配分类的详细属性字段
- 调用 search_ontology_models 查找该分类下是否存在对应的行为（M_BEHAVIOR）或规则（M_RULE）

### 第3步：分支执行 — 根据第2步结果选择路径

**路径A：找到了对应的行为或规则** → 调用 call_reasoner 使用推理机进行推理：
  - 先调用 list_reasoner_tools 查看可用推理工具
  - 然后调用 call_reasoner（工具名尝试: infer_forward, validate, check_rule, expand）
  - 推理机返回的结果即为最终的推理结论

**路径B：没有找到对应的行为或规则** → 采用以下两种方式协同处理：
  1. 调用 search_knowledge_graph 和 traverse_graph（最多4层），利用图谱中的静态关系进行分析
  2. 如果图谱数据不足，自行拆分任务，将用户问题拆解为子步骤逐步推理

### 第4步：方案输出
用以下格式输出最终方案：
```
## 目标理解
...
## 本体匹配
（匹配到的本体分类及原因）
## 推理路径
（说明走了路径A还是路径B，以及关键依据）
## 执行步骤
1. xxx [依据: xxx]
2. xxx [依据: xxx]
## 风险与假设
...
```

## 重要约束
- 必须先查本体分类，再决定后续执行路径，不要跳过
- 优先使用图谱中已有数据，再补充 LLM 知识
- 推理机返回结果应直接采纳，不要重复验证（除非结果明显不合理）
- 用中文回答
"""

# =============================================================================
# Agent Tools
# =============================================================================

@tool
async def search_knowledge_graph(keyword: str) -> str:
    """
    在图数据库（Memgraph）中搜索实体。返回匹配的节点及其属性。

    Args:
        keyword: 搜索关键词（实体名称、编码等）
    """
    import time
    from infrastructure.db.neo4j import get_driver
    from capabilities.memory.graph_memory import GraphMemory
    from common.utils.metrics import get_metrics

    metrics = get_metrics()
    start = time.perf_counter()
    try:
        driver = await get_driver()
        graph = GraphMemory(driver)
        nodes = await graph.search_nodes(keyword, limit=30)
        elapsed = (time.perf_counter() - start) * 1000
        metrics.record("search_knowledge_graph", elapsed, success=True)
        if not nodes:
            return f"未找到与 '{keyword}' 相关的实体。"
        result = []
        for n in nodes:
            props = n.get("properties", {})
            labels = n.get("labels", [])
            result.append({
                "id": n.get("id"),
                "labels": labels,
                "name": props.get("name", ""),
                "type": props.get("type", ""),
                "properties": {k: v for k, v in props.items() if k not in ("name", "type") and v},
            })
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000
        metrics.record("search_knowledge_graph", elapsed, success=False)
        return json.dumps({"ok": False, "error": str(e), "fallback": "请检查图数据库连接状态或使用 search_ontology_models 替代"}, ensure_ascii=False)


@tool
async def traverse_graph(entity_name: str, depth: int = 4) -> str:
    """
    从指定实体出发，在图谱中遍历关系网络，最多遍历 depth 层。
    当推理机调用失败时，本工具作为主要降级路径。

    Args:
        entity_name: 起始实体名称
        depth: 遍历深度（1-4，默认 4）
    """
    import time
    from infrastructure.db.neo4j import get_driver
    from common.utils.metrics import get_metrics

    metrics = get_metrics()
    depth = max(1, min(depth, 4))
    start = time.perf_counter()
    try:
        driver = await get_driver()
        async with driver.session() as session:
            find = await session.run(
                "MATCH (n {name: $name}) RETURN id(n) AS nid LIMIT 1",
                name=entity_name,
            )
            rec = await find.single()
            if not rec:
                elapsed = (time.perf_counter() - start) * 1000
                metrics.record("traverse_graph", elapsed, success=True)
                return f"未找到名为 '{entity_name}' 的实体。"

            node_id = rec["nid"]
            result = await session.run(
                f"""
                MATCH (n) WHERE id(n) = $node_id
                OPTIONAL MATCH path = (n)-[*1..{depth}]-(m)
                WITH n, m, relationships(path) AS rels, length(path) AS dist
                WHERE m IS NOT NULL
                RETURN collect(DISTINCT {{
                    path_length: dist,
                    target_name: m.name,
                    target_type: m.type,
                    relation: type(rels[0]),
                    relation_type: rels[0].type
                }}) AS neighbors
                """,
                node_id=node_id,
            )
            record = await result.single()
            neighbors = record["neighbors"] if record else []
            elapsed = (time.perf_counter() - start) * 1000
            metrics.record("traverse_graph", elapsed, success=True)
            return json.dumps({
                "entity": entity_name,
                "depth": depth,
                "neighbor_count": len(neighbors),
                "relationships": neighbors,
            }, ensure_ascii=False, indent=2)
    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000
        metrics.record("traverse_graph", elapsed, success=False)
        return json.dumps({"ok": False, "error": str(e), "fallback": "请使用 search_knowledge_graph 查找实体后手动分析"}, ensure_ascii=False)


@tool
async def search_ontology_models(keyword: str) -> str:
    """
    在本体模型库（SQLite）中搜索本体模型定义。

    Args:
        keyword: 搜索关键词（本体名称、编码、描述）
    """
    import sqlite3
    from pathlib import Path

    try:
        db_path = Path("infrastructure/db/ontol.db")
        if not db_path.exists():
            return "本体模型库不可用。"

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT id, ontol_parent_id, name, ontol_data_type,
                      ontol_model_status, ontol_model_desc
               FROM ontol_model
               WHERE delete_flag = '0'
                 AND (name LIKE ? OR ontol_model_desc LIKE ? OR id LIKE ?)
               LIMIT 30""",
            (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"),
        ).fetchall()
        conn.close()

        if not rows:
            return f"未找到与 '{keyword}' 相关的本体模型。"
        return json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2)
    except Exception as e:
        return f"本体模型查询失败: {e}"


@tool
async def get_ontology_tree(root_id: str = "M_ROOT") -> str:
    """
    获取本体模型的完整层级树，包含每个节点的属性定义。

    Args:
        root_id: 根模型ID，默认 M_ROOT
    """
    import sqlite3
    from pathlib import Path

    try:
        db_path = Path("infrastructure/db/ontol.db")
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        rows = conn.execute(
            """WITH RECURSIVE tree AS (
                SELECT m.*, 0 AS depth
                FROM ontol_model m
                WHERE m.id = ? AND m.delete_flag = '0'
                UNION ALL
                SELECT m.*, t.depth + 1
                FROM ontol_model m
                INNER JOIN tree t ON m.ontol_parent_id = t.id
                WHERE m.delete_flag = '0'
            )
            SELECT * FROM tree ORDER BY depth, ontol_data_type, name""",
            (root_id,),
        ).fetchall()

        tree = []
        for r in rows:
            node = dict(r)
            # Get attributes for this model
            attrs = conn.execute(
                """SELECT name, code, attr_data_type, attr_length,
                          attr_required, attr_default_value, attr_desc
                   FROM ontol_model_attr
                   WHERE ontol_model_id = ? AND delete_flag = '0'
                   ORDER BY code""",
                (node["id"],),
            ).fetchall()
            node["attributes"] = [dict(a) for a in attrs]
            tree.append(node)

        conn.close()
        return json.dumps(tree, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"本体树查询失败: {e}"


@tool
async def get_model_detail(model_id: str) -> str:
    """
    获取指定本体模型的详细属性字段定义。

    Args:
        model_id: 模型ID（如 M_ENTITY, M_BEHAVIOR, M_ROOT 等）
    """
    import sqlite3
    from pathlib import Path

    try:
        db_path = Path("infrastructure/db/ontol.db")
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        model = conn.execute(
            "SELECT * FROM ontol_model WHERE id = ? AND delete_flag = '0'",
            (model_id,),
        ).fetchone()

        if not model:
            conn.close()
            return f"未找到模型 '{model_id}'。"

        attrs = conn.execute(
            """SELECT name, code, attr_data_type, attr_length,
                      attr_required, attr_default_value, attr_desc, attr_is_system
               FROM ontol_model_attr
               WHERE ontol_model_id = ? AND delete_flag = '0'
               ORDER BY code""",
            (model_id,),
        ).fetchall()

        conn.close()
        return json.dumps({
            "model": dict(model),
            "attributes": [dict(a) for a in attrs],
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"模型详情查询失败: {e}"


@tool
def call_reasoner(tool_name: str = "infer_forward", params: str = "{}") -> str:
    """
    调用外部知识图谱推理机。可用的推理工具由 KG 服务器提供。

    内置降级策略:
    - 连接拒绝 → 标记为可恢复，引导 LLM 使用 traverse_graph
    - 400 错误  → 解析推理机返回的 error 详情，反馈给 LLM 修正参数
    - 超时      → 降级到图谱遍历

    Args:
        tool_name: 推理工具名（如 infer_forward, validate, check_rule, expand）
        params: JSON 格式的参数字符串，如 '{"code": "Entity.code", "depth": 2}'
    """
    import requests
    import time
    from common.utils.metrics import get_metrics
    from common.exceptions import ReasonerError

    metrics = get_metrics()
    settings = get_settings()
    server = settings.kg_server_url

    try:
        arguments = json.loads(params) if isinstance(params, str) else params
    except json.JSONDecodeError:
        arguments = {}

    start = time.perf_counter()
    try:
        resp = requests.post(
            f"{server}/tools/call",
            json={"name": tool_name, "arguments": arguments},
            timeout=30,
        )
        elapsed = (time.perf_counter() - start) * 1000

        if resp.status_code == 400:
            # 推理机返回的业务错误（如 Entity not found），提取详情供 LLM 修正
            try:
                err_body = resp.json()
                error_msg = err_body.get("error", resp.text)
            except Exception:
                error_msg = resp.text
            metrics.record("call_reasoner", elapsed, success=False)
            return json.dumps({
                "ok": False,
                "error": error_msg,
                "tool": tool_name,
                "fallback": "请尝试以下操作：\n"
                            "1. 修正参数后重试（确认 entity code/name 是否存在）\n"
                            "2. 调用 search_knowledge_graph 搜索正确的实体\n"
                            "3. 使用 traverse_graph 直接在图谱中遍历关系",
            }, ensure_ascii=False)

        resp.raise_for_status()
        metrics.record("call_reasoner", elapsed, success=True)
        result = resp.text
        try:
            return json.dumps(json.loads(result), ensure_ascii=False, indent=2)
        except (json.JSONDecodeError, TypeError):
            return result[:2000]

    except requests.ConnectionError:
        elapsed = (time.perf_counter() - start) * 1000
        metrics.record("call_reasoner", elapsed, success=False)
        return json.dumps({
            "ok": False,
            "error": f"推理机不可达 ({server})",
            "tool": tool_name,
            "fallback": "推理机连接失败，请使用 traverse_graph 在图谱中遍历关系，"
                        "或使用 search_knowledge_graph 查找相关实体。",
        }, ensure_ascii=False)

    except requests.Timeout:
        elapsed = (time.perf_counter() - start) * 1000
        metrics.record("call_reasoner", elapsed, success=False)
        return json.dumps({
            "ok": False,
            "error": "推理机调用超时 (30s)",
            "tool": tool_name,
            "fallback": "推理机响应超时，请使用 traverse_graph 替代推理。",
        }, ensure_ascii=False)

    except requests.RequestException as e:
        elapsed = (time.perf_counter() - start) * 1000
        metrics.record("call_reasoner", elapsed, success=False)
        return json.dumps({
            "ok": False,
            "error": str(e),
            "tool": tool_name,
            "fallback": "请使用 traverse_graph 或 search_knowledge_graph 替代推理机。",
        }, ensure_ascii=False)


@tool
def list_reasoner_tools() -> str:
    """
    列出推理机提供的所有可用工具。
    """
    import requests

    settings = get_settings()
    server = settings.kg_server_url

    try:
        resp = requests.get(f"{server}/tools", timeout=10)
        resp.raise_for_status()
        tools_list = resp.json()
        return json.dumps(tools_list, ensure_ascii=False, indent=2)
    except requests.ConnectionError:
        return f"推理机不可达 ({server})。"
    except requests.RequestException as e:
        return f"获取推理工具列表失败: {e}"


# =============================================================================
# Agent 创建
# =============================================================================

AGENT_TOOLS = [
    search_knowledge_graph,
    traverse_graph,
    search_ontology_models,
    get_ontology_tree,
    get_model_detail,
    call_reasoner,
    list_reasoner_tools,
]


def _build_dynamic_prompt(scene_prompts: list[dict]) -> str:
    """构建动态系统提示词：基础 SYSTEM_PROMPT + 场景提示词目录。

    Agent 会根据用户意图自动匹配 prompt_description，选择最合适的模板。
    """
    if not scene_prompts:
        return SYSTEM_PROMPT

    catalog_parts = []
    for i, p in enumerate(scene_prompts, 1):
        desc = p.get("prompt_description") or p.get("prompt_desc") or ""
        content = p.get("prompt_content") or ""
        if not content:
            continue
        catalog_parts.append(
            f"### 模板{i}: {p.get('name', '未命名')}\n"
            f"**调用时机**: {desc}\n"
            f"**内容**:\n{content}"
        )

    if not catalog_parts:
        return SYSTEM_PROMPT

    catalog = "\n\n".join(catalog_parts)
    return SYSTEM_PROMPT + f"""

---
## 可用场景提示词模板

当前对话绑定了一个或多个场景，每个场景提供了针对性的提示词模板。你需要根据用户的问题和意图，动态选择最合适的模板来执行任务。

{catalog}

---
**路由规则（必须遵守）**:
1. 分析用户最新的问题，判断它是否匹配某个模板的"调用时机"描述
2. 如果匹配，严格遵循该模板的"内容"来执行任务（模板内容优先级高于默认管道流程）
3. 如果不匹配任何模板，或者模板内容与当前任务无关，使用默认的管道流程（6步推理）
4. 在一次对话中，随着用户意图变化，可以动态切换不同的模板
5. 每次回复时，简单说明你正在使用哪个模板（或使用默认流程）
"""


async def create_chat_agent(
    model_name: str = "",
    scene_prompts: list[dict] | None = None,
):
    """创建配置好工具和系统提示的 ReAct Agent。

    Args:
        model_name: LLM 模型 config_id (ontol_llm_config.id)。
        scene_prompts: 场景提示词列表 [{name, prompt_description, prompt_content}]。
                       如果提供，Agent 会根据用户意图动态匹配。
    """
    from capabilities.models.factory import ModelFactory
    import sqlite3
    from pathlib import Path

    if not model_name:
        raise ValueError("未指定模型名称")

    factory = ModelFactory()
    db_path = Path("infrastructure/db/ontol.db")
    if not db_path.exists():
        raise RuntimeError("数据库未就绪")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM ontol_llm_config WHERE id=? AND delete_flag='0'", (model_name,)
    ).fetchone()
    conn.close()

    if not row:
        raise ValueError(f"模型配置 {model_name} 不存在")

    llm_iface = factory.create_llm_from_config(
        base_url=row["llm_url"] or "",
        api_key=row["llm_key"] or "",
        model_name=row["llm_model"] or row["name"],
    )
    llm = await llm_iface.get_llm()

    prompt = _build_dynamic_prompt(scene_prompts or [])
    agent = create_react_agent(model=llm, tools=AGENT_TOOLS, prompt=prompt)
    return agent


async def run_chat_agent(
    messages: list[dict],
    model_name: str = "",
    scene_prompts: list[dict] | None = None,
) -> AsyncIterator[dict]:
    """
    运行 Chat Agent 管道，流式返回结果。

    Args:
        messages: 对话消息列表。
        model_name: LLM 模型 config_id。
        scene_prompts: 场景提示词列表，由 Agent 动态匹配。

    Yields:
        {"type": "content", "content": "..."}
        {"type": "tool_call", "tool": "...", "args": {...}}
        {"type": "tool_result", "tool": "...", "result": "..."}
        {"type": "error", "error": "..."}
        {"type": "done"}
    """
    from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

    agent = await create_chat_agent(model_name, scene_prompts=scene_prompts)

    # 转换消息格式
    lc_messages = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "user":
            lc_messages.append(HumanMessage(content=content))
        elif role == "assistant":
            lc_messages.append(AIMessage(content=content))
        elif role == "system":
            lc_messages.append(SystemMessage(content=content))

    # 使用 astream_events 获取详细的流式事件
    try:
        async for event in agent.astream_events(
            {"messages": lc_messages},
            version="v2",
        ):
            kind = event.get("event", "")

            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk", None)
                if chunk and hasattr(chunk, "content") and chunk.content:
                    yield {"type": "content", "content": chunk.content}

            elif kind == "on_tool_start":
                tool_name = event.get("name", "unknown")
                tool_input = event.get("data", {}).get("input", {})
                yield {"type": "tool_call", "tool": tool_name, "args": tool_input}

            elif kind == "on_tool_end":
                tool_name = event.get("name", "unknown")
                output = event.get("data", {}).get("output", "")
                # Extract actual content from ToolMessage
                if hasattr(output, "content"):
                    result_str = str(output.content)[:2000]
                else:
                    result_str = str(output)[:2000] if output else ""
                yield {"type": "tool_result", "tool": tool_name, "result": result_str}

    except Exception as e:
        yield {"type": "error", "error": str(e)}

    yield {"type": "done"}
