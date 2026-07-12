"""
SHACL → Cypher 转换器
----------------------
将 SHACL 约束转为 Memgraph Cypher 验证查询。

SHACL 约束类型:
  sh:property    — 属性存在约束
  sh:class       — 节点类型约束
  sh:datatype    — 数据类型约束 (xsd:string, xsd:integer, ...)
  sh:minCount    — 最小出现次数
  sh:maxCount    — 最大出现次数
  sh:pattern     — 正则匹配
  sh:in          — 枚举值约束
  sh:nodeKind    — 节点类型 (sh:IRI / sh:BlankNode / sh:Literal)
"""

SH_PREFIX = "sh:"
XSD_STRING = "xsd:string"
XSD_INTEGER = "xsd:integer"
XSD_FLOAT = "xsd:float"
XSD_BOOLEAN = "xsd:boolean"
XSD_DATE = "xsd:date"


# ================================================================
# SHACL 约束类型枚举
# ================================================================

SHACL_PROPERTY = "sh:property"     # 属性存在约束
SHACL_CLASS = "sh:class"           # 节点类型约束
SHACL_DATATYPE = "sh:datatype"     # 数据类型约束
SHACL_MIN_COUNT = "sh:minCount"    # 最小出现次数
SHACL_MAX_COUNT = "sh:maxCount"    # 最大出现次数
SHACL_PATTERN = "sh:pattern"       # 正则匹配
SHACL_IN = "sh:in"                 # 枚举值
SHACL_NODE_KIND = "sh:nodeKind"    # 节点类型
SHACL_PATH = "sh:path"             # 属性路径


# ================================================================
# 单条约束 → Cypher
# ================================================================

def property_exists_cypher(prop_name: str, node_var: str = "n") -> str:
    """sh:property — 属性必须存在。"""
    return f"MATCH ({node_var}) WHERE {node_var}.{prop_name} IS NOT NULL RETURN count({node_var}) AS valid"


def class_check_cypher(expected_label: str, node_var: str = "n") -> str:
    """sh:class — 节点必须属于指定类型。"""
    return f"MATCH ({node_var}:`{expected_label}`) RETURN count({node_var}) AS valid"


def datatype_check_cypher(prop_name: str, xsd_type: str, node_var: str = "n") -> str:
    """sh:datatype — 属性值必须符合 XSD 数据类型。"""
    type_check = {
        XSD_INTEGER: f"toInteger({node_var}.{prop_name}) IS NOT NULL",
        XSD_FLOAT:   f"toFloat({node_var}.{prop_name}) IS NOT NULL",
        XSD_BOOLEAN: f"toBoolean({node_var}.{prop_name}) IS NOT NULL",
    }
    check = type_check.get(xsd_type, f"{node_var}.{prop_name} IS NOT NULL")
    return f"MATCH ({node_var}) WHERE {check} RETURN count({node_var}) AS valid"


def min_count_cypher(prop_name: str, min_val: int, node_var: str = "n") -> str:
    """sh:minCount — 属性最少出现次数（数组长度 >= min）。"""
    return f"MATCH ({node_var}) WHERE size({node_var}.{prop_name}) >= {min_val} RETURN count({node_var}) AS valid"


def max_count_cypher(prop_name: str, max_val: int, node_var: str = "n") -> str:
    """sh:maxCount — 属性最多出现次数。"""
    return f"MATCH ({node_var}) WHERE size({node_var}.{prop_name}) <= {max_val} RETURN count({node_var}) AS valid"


def pattern_cypher(prop_name: str, regex: str, node_var: str = "n") -> str:
    """sh:pattern — 正则匹配。"""
    escaped_regex = regex.replace("'", "\\'")
    return f"MATCH ({node_var}) WHERE {node_var}.{prop_name} =~ '{escaped_regex}' RETURN count({node_var}) AS valid"


def enum_cypher(prop_name: str, values: list[str], node_var: str = "n") -> str:
    """sh:in — 枚举值约束。"""
    vals = ", ".join(f"'{v}'" for v in values)
    return f"MATCH ({node_var}) WHERE {node_var}.{prop_name} IN [{vals}] RETURN count({node_var}) AS valid"


# ================================================================
# 批量 SHACL 约束 → 验证 Cypher
# ================================================================

def validate_node_cypher(node_id: int, constraints: list[dict]) -> str:
    """
    对一个节点执行多个 SHACL 约束验证。

    参数 constraints:
      [{"type": "sh:property", "prop": "name"},
       {"type": "sh:datatype", "prop": "age", "xsd": "xsd:integer"},
       {"type": "sh:minCount", "prop": "tags", "min": 1}]

    返回一个 UNION 查询，每条返回 valid 计数。
    """
    parts = []
    for c in constraints:
        ctype = c.get("type", "")
        prop = c.get("prop", "name")
        if ctype == SHACL_PROPERTY:
            parts.append(f"MATCH (n) WHERE id(n) = {node_id} AND n.{prop} IS NOT NULL RETURN '{ctype}:{prop}' AS constraint, 1 AS valid")
        elif ctype == SHACL_DATATYPE:
            parts.append(f"MATCH (n) WHERE id(n) = {node_id} AND toFloat(n.{prop}) IS NOT NULL RETURN '{ctype}:{prop}' AS constraint, 1 AS valid")
        elif ctype == SHACL_MIN_COUNT:
            min_v = c.get("min", 1)
            parts.append(f"MATCH (n) WHERE id(n) = {node_id} AND size(n.{prop}) >= {min_v} RETURN '{ctype}:{prop}' AS constraint, 1 AS valid")
        elif ctype == SHACL_MAX_COUNT:
            max_v = c.get("max", 99)
            parts.append(f"MATCH (n) WHERE id(n) = {node_id} AND size(n.{prop}) <= {max_v} RETURN '{ctype}:{prop}' AS constraint, 1 AS valid")
    if not parts:
        return "RETURN 'no constraints' AS constraint, 1 AS valid"
    return "\nUNION ALL\n".join(parts)


def is_shacl_expression(value: str) -> bool:
    """判断是否为 SHACL 表达式。"""
    return value.strip().startswith(SH_PREFIX)
