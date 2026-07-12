"""
func → Cypher + Python 转换器
-------------------------------
动态函数调用：不对接大模型，用 JSON 配置调用 Python 函数实现。

格式:
  func:{"id":"图ID","func":"函数名"}

流程:
  1. 解析 JSON → 提取 id + func
  2. 按 id 查 Memgraph 节点
  3. 按 func 名路由到对应 Python 函数
  4. 执行函数，结果写回图节点属性
"""

import json as _json
from typing import Any, Callable

FUNC_PREFIX = "func:"


# ================================================================
# 解析
# ================================================================

def parse_func(value: str) -> dict:
    """解析 func:{"id":"xxx","func":"yyy"} → {id, func}。"""
    v = value.strip()
    json_str = v[len(FUNC_PREFIX):] if v.startswith(FUNC_PREFIX) else v
    try:
        return _json.loads(json_str)
    except _json.JSONDecodeError:
        return {"raw": json_str}


# ================================================================
# 函数注册表
# ================================================================

class FuncRegistry:
    """动态函数注册中心。"""

    def __init__(self):
        self._funcs: dict[str, Callable] = {}

    def register(self, name: str, fn: Callable) -> None:
        self._funcs[name] = fn

    def get(self, name: str) -> Callable:
        return self._funcs.get(name)

    def has(self, name: str) -> bool:
        return name in self._funcs


# 全局单例
func_registry = FuncRegistry()


# ================================================================
# Cypher 生成
# ================================================================

def func_lookup_cypher(graph_id: str) -> str:
    """按 ID 查目标节点。"""
    return f"""
    MATCH (n) WHERE n.id = '{graph_id}' OR id(n) = toInteger('{graph_id}')
    RETURN id(n) AS id, labels(n) AS labels, properties(n) AS props
    """


def func_writeback_cypher(node_id: int, result: dict) -> str:
    """将函数执行结果写回节点属性。"""
    set_clauses = ", ".join(f"n.{k} = ${k}" for k in result)
    return f"""
    MATCH (n) WHERE id(n) = {node_id}
    SET {set_clauses}
    RETURN n
    """


def is_func_expression(value: str) -> bool:
    """判断是否为 func 表达式。"""
    return value.strip().startswith(FUNC_PREFIX)
