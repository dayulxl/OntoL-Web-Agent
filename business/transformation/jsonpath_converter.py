"""
JSONPath → Cypher 转换器
--------------------------
将 JSONPath (RFC 9535) 表达式转为 Cypher 属性访问。

格式:
  $.node1.node1-1 → n.node1_node1_1  (嵌套 JSON key)

Cypher 中的 JSON 属性用 . 访问:
  n.prop = '{"a":{"b":1}}'
  $.a.b → apoc.convert.fromJsonMap(n.prop).a.b

Memgraph 原生支持 JSON 属性，可以直接点号访问嵌套。
"""

import re as _re

JSONPATH_PREFIX = "$."


# ================================================================
# 解析
# ================================================================

def parse_jsonpath(expression: str) -> list[str]:
    """
    解析 JSONPath 为路径段数组。
    "$.store.book[0].title" → ["store", "book", "0", "title"]
    "$.node1.sub-node"      → ["node1", "sub-node"]
    """
    v = expression.strip()
    if v.startswith(JSONPATH_PREFIX):
        v = v[2:]
    # 去掉数组索引 [n]
    v = _re.sub(r'\[\d+\]', '.', v)
    # 按 . 拆分
    segments = [s.strip() for s in v.split(".") if s.strip()]
    return segments


# ================================================================
# 属性访问
# ================================================================

def jsonpath_get_cypher(expression: str, node_var: str = "n") -> str:
    """
    JSONPath → Cypher 属性读取。

    $.ont_type → RETURN n.ont_type
    $.store.book.title → RETURN n.store.book.title  (嵌套 JSON)
    """
    segs = parse_jsonpath(expression)
    if not segs:
        return f"RETURN {node_var}"
    path = ".".join(segs)
    return f"MATCH ({node_var}) RETURN {node_var}.{path} AS value"


def jsonpath_set_cypher(expression: str, value, node_var: str = "n") -> str:
    """JSONPath → Cypher 属性写入。"""
    segs = parse_jsonpath(expression)
    if not segs:
        return ""
    path = ".".join(segs)
    return f"MATCH ({node_var}) SET {node_var}.{path} = $value RETURN {node_var}"


# ================================================================
# 条件查询
# ================================================================

def jsonpath_condition_cypher(expression: str, operator: str, value, node_var: str = "n") -> str:
    """
    JSONPath 条件查询 → Cypher WHERE 子句。
    $.confidence > 0.5 → WHERE n.confidence > 0.5
    $.status = "active" → WHERE n.status = 'active'
    """
    segs = parse_jsonpath(expression)
    if not segs:
        return ""
    path = ".".join(segs)
    if isinstance(value, str) and not value.startswith("'"):
        value = f"'{value}'"
    return f"MATCH ({node_var}) WHERE {node_var}.{path} {operator} {value} RETURN {node_var}"


def is_jsonpath_expression(value: str) -> bool:
    """判断是否为 JSONPath 表达式。"""
    return value.strip().startswith(JSONPATH_PREFIX)
