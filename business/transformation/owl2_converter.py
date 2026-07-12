"""
OWL2 DL → Cypher 转换器
------------------------
将 OWL2 DL 语义转为 Memgraph Cypher 查询。
支持：subClassOf 链、equivalentClass、disjointWith、inverseOf、
      sameAs/differentFrom、objectProperty/dataProperty、domain/range。
"""

from business.reasoning.graph_ops import get_outgoing_by_rel_type, run_cypher

OWL2_PREFIX = "owl2:"

# OWL2 关系类型（不带前缀的 Cypher 兼容形式）
OWL2_SUBCLASS_OF = "owl2:subClassOf"
OWL2_EQUIVALENT = "owl2:equivalentClass"
OWL2_DISJOINT = "owl2:disjointWith"
OWL2_INVERSE = "owl2:inverseOf"
OWL2_SAME_AS = "owl2:sameAs"
OWL2_DIFFERENT = "owl2:differentFrom"
OWL2_OBJECT_PROP = "owl2:objectProperty"
OWL2_DATA_PROP = "owl2:dataProperty"
OWL2_DOMAIN = "owl2:domain"
OWL2_RANGE = "owl2:range"


# ================================================================
# subClassOf 祖先链爬取
# ================================================================

async def climb_subclass_chain(node_id: int, visited: set = None) -> list[dict]:
    """
    沿 owl2:subClassOf 递归上爬，返回 [最顶层, ..., 直接父类]。
    这是 OWL2 语义的核心：subClassOf → 子类型继承父类型所有属性。

    算法：递归沿 owl2:subClassOf 边上爬，直到顶层（无父类）。
    返回列表已去重并排好序（顶层在前）。

    图示意:
        A --subClassOf--> B --subClassOf--> C --subClassOf--> D(顶层)
                                          ↑ 种子
        climb 结果: [D, C, B]  (不含 A 自身)
    """
    if visited is None:
        visited = set()
    if node_id in visited:
        return []
    visited.add(node_id)

    parents = await get_outgoing_by_rel_type(node_id, OWL2_SUBCLASS_OF)
    chain = []
    for p in parents:
        upper = await climb_subclass_chain(p["id"], visited)
        chain.extend(upper)
        chain.append(p)
    return chain


def build_subclass_cypher(node_id: int) -> str:
    """
    生成爬取 owl2:subClassOf 链的 Cypher 语句。
    用于一次性获取完整祖先链（可选方案，替代递归 Python 版本）。
    """
    return f"""
    MATCH path = (n)-[:`{OWL2_SUBCLASS_OF}`*]->(ancestor)
    WHERE id(n) = {node_id}
    RETURN nodes(path) AS ancestors
    ORDER BY length(path) DESC
    """


# ================================================================
# equivalentClass
# ================================================================

def equivalent_class_cypher(node_id: int) -> str:
    """查找与当前节点等价的类型。"""

    return f"""
    MATCH (n)-[r]-(eq)
    WHERE id(n) = {node_id}
      AND (type(r) = '{OWL2_EQUIVALENT}' OR r.actionType = '{OWL2_EQUIVALENT}')
    RETURN id(eq) AS id, labels(eq) AS labels, properties(eq) AS props
    """


# ================================================================
# disjointWith
# ================================================================

def disjoint_with_cypher(node_id: int) -> str:
    """查找与当前节点互斥的类型（检查是否有冲突）。"""
    return f"""
    MATCH (n)-[r]-(dis)
    WHERE id(n) = {node_id}
      AND (type(r) = '{OWL2_DISJOINT}' OR r.actionType = '{OWL2_DISJOINT}')
    RETURN id(dis) AS id, labels(dis) AS labels, properties(dis) AS props
    """


# ================================================================
# inverseOf
# ================================================================

def inverse_of_cypher(node_id: int, rel_type: str = None) -> str:
    """查找逆关系，可选指定关系类型。"""
    rel_filter = f"AND type(r) = '{rel_type}'" if rel_type else ""
    return f"""
    MATCH (n)-[r]-(inv)
    WHERE id(n) = {node_id}
      AND (type(r) = '{OWL2_INVERSE}' OR r.actionType = '{OWL2_INVERSE}')
      {rel_filter}
    RETURN inv, properties(inv) AS props
    """


# ================================================================
# 属性继承 (OWL2 subClassOf 语义)
# ================================================================

def inherit_properties_cypher(ancestor_chain: list[dict], seed: dict) -> dict:
    """
    OWL2 subClassOf 属性继承规则：
    顶层祖先属性为基底 → 逐层覆盖 → 子节点最后扩展。

    继承链: [D(顶层), C, B] + A(种子)
    结果: D.props ∪ C.props ∪ B.props ∪ A.props (后覆盖前)
    """
    from business.reasoning.graph_ops import merge_inherited_props
    return merge_inherited_props(ancestor_chain, seed)


# ================================================================
# domain / range 约束
# ================================================================

def domain_range_cypher(prop_name: str) -> str:
    """查属性的 domain 和 range 约束。"""
    return f"""
    MATCH (n)-[r]->(m)
    WHERE type(r) = '{prop_name}'
    OPTIONAL MATCH (domain)-[:`{OWL2_DOMAIN}`]->(n)
    OPTIONAL MATCH (m)-[:`{OWL2_RANGE}`]->(range)
    RETURN domain, range, properties(domain) AS domain_props, properties(range) AS range_props
    """


# ================================================================
# 类型检索
# ================================================================

def find_by_type_cypher(ont_type: str, limit: int = 100) -> str:
    """按 ont_type 查找所有实例。"""
    return f"""
    MATCH (n {{ont_type: '{ont_type}'}})
    RETURN id(n) AS id, labels(n) AS labels, properties(n) AS props
    LIMIT {limit}
    """
