"""
RDFS → Cypher 转换器
--------------------
RDFS 核心常量 + 属性 → Cypher 查询。
支持：rdfs:domain、rdfs:range、rdfs:subClassOf、rdfs:subPropertyOf、
      rdfs:label、rdfs:comment、rdfs:seeAlso、rdfs:isDefinedBy。

注意：subClassOf 链爬取由 owl2_converter 处理（OWL2 扩展了 RDFS）。
      本模块处理 RDFS 原生词汇的 Cypher 转换。
"""

from business.reasoning.graph_ops import run_cypher

RDFS_PREFIX = "rdfs:"

# RDFS 核心词汇
RDFS_DOMAIN = "rdfs:domain"
RDFS_RANGE = "rdfs:range"
RDFS_SUBCLASS_OF = "rdfs:subClassOf"
RDFS_SUBPROPERTY_OF = "rdfs:subPropertyOf"
RDFS_LABEL = "rdfs:label"
RDFS_COMMENT = "rdfs:comment"
RDFS_SEE_ALSO = "rdfs:seeAlso"
RDFS_IS_DEFINED_BY = "rdfs:isDefinedBy"

# RDFS 核心常量（不写前缀也支持）
RDFS_CONSTANTS = {
    "Resource":   "rdfs:Resource",    # 万物之父
    "Class":      "rdfs:Class",
    "Literal":    "rdfs:Literal",
    "Datatype":   "rdfs:Datatype",
    "Container":  "rdfs:Container",
}


# ================================================================
# 属性 domain/range 查询
# ================================================================

def domain_cypher(prop_name: str) -> str:
    """查询某个属性的 domain（定义域）。"""
    return f"""
    MATCH (n)-[r]-(domain)
    WHERE (type(r) = '{prop_name}' AND r.actionType = '{RDFS_DOMAIN}')
       OR (type(r) = '{RDFS_DOMAIN}' AND r.id = '{prop_name}')
    RETURN domain, properties(domain) AS props
    """


def range_cypher(prop_name: str) -> str:
    """查询某个属性的 range（值域）。"""
    return f"""
    MATCH (n)-[r]-(range)
    WHERE (type(r) = '{prop_name}' AND r.actionType = '{RDFS_RANGE}')
       OR (type(r) = '{RDFS_RANGE}' AND r.id = '{prop_name}')
    RETURN range, properties(range) AS props
    """


# ================================================================
# subPropertyOf
# ================================================================

def subproperty_chain_cypher(node_id: int) -> str:
    """爬取 rdfs:subPropertyOf 链（属性的继承层次）。"""
    return f"""
    MATCH path = (n)-[:`{RDFS_SUBPROPERTY_OF}`*]->(super_prop)
    WHERE id(n) = {node_id}
    RETURN nodes(path) AS chain, length(path) AS depth
    ORDER BY depth DESC
    """


# ================================================================
# 标签/注释
# ================================================================

def label_comment_cypher(node_id: int) -> str:
    """获取节点的 rdfs:label 和 rdfs:comment。"""
    return f"""
    MATCH (n)
    WHERE id(n) = {node_id}
    RETURN n.{RDFS_LABEL} AS label, n.{RDFS_COMMENT} AS comment,
           n.{RDFS_SEE_ALSO} AS see_also, n.{RDFS_IS_DEFINED_BY} AS defined_by
    """


# ================================================================
# 本体语言识别
# ================================================================

def is_rdfs_expression(value: str) -> bool:
    """判断字符串是否为 RDFS 表达（rdfs: 前缀或不写前缀的核心常量）。"""
    v = value.strip()
    if v.startswith(RDFS_PREFIX):
        return True
    if v in RDFS_CONSTANTS:
        return True
    return False


def normalize_rdfs(value: str) -> str:
    """将不写前缀的 RDFS 核心常量补全为 rdfs: 前缀形式。"""
    v = value.strip()
    return RDFS_CONSTANTS.get(v, v)
