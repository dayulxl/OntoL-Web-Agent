"""
Rule → Cypher 转换器
---------------------
推理方向设定 + 推理策略 → Cypher 遍历语句。

格式:
  rule:forwardChain   → 前链推理（默认）：从种子沿 inference 边走到底
  rule:backwardChain  → 后链推理：从目标反推回种子

Cypher 产出:
  forwardChain  → MATCH path = (seed)-[r* {actionType:"inference"}]->(leaf)
  backwardChain → MATCH path = (seed)<-[r* {actionType:"inference"}]-(root)
"""

RULE_PREFIX = "rule:"
FORWARD_CHAIN = "forwardChain"
BACKWARD_CHAIN = "backwardChain"


def parse_direction(value: str) -> str:
    """从 rule:xxx 提取方向。"""
    return value.strip().replace(RULE_PREFIX, "")


def direction_from_edge(edge_props: dict) -> str:
    """
    从边的 ruleId 属性推断推理方向。
    默认 forwardChain。
    """
    rule_id = edge_props.get("ruleId", "")
    if not rule_id:
        return FORWARD_CHAIN
    return parse_direction(rule_id)


# ================================================================
# 前链推理 Cypher
# ================================================================

def forward_chain_cypher(seed_id: int, max_depth: int = 10) -> str:
    """
    从种子节点沿 actionType="inference" 边正向遍历，返回完整路径。
    这是默认推理模式：已知事实 → 新结论。
    """
    return f"""
    MATCH path = (seed)-[r*..{max_depth}]->(target)
    WHERE id(seed) = {seed_id}
      AND all(rel IN r WHERE rel.actionType = 'inference')
    RETURN nodes(path) AS chain, relationships(path) AS edges,
           length(path) AS depth
    ORDER BY depth
    """


# ================================================================
# 后链推理 Cypher
# ================================================================

def backward_chain_cypher(seed_id: int, max_depth: int = 10) -> str:
    """
    从种子节点反向查找所有指向它的 inference 边。
    目标 → 反推到支撑条件。
    """
    return f"""
    MATCH path = (source)-[r*..{max_depth}]->(target)
    WHERE id(target) = {seed_id}
      AND all(rel IN r WHERE rel.actionType = 'inference')
    RETURN nodes(path) AS chain, relationships(path) AS edges,
           length(path) AS depth
    ORDER BY depth
    """


# ================================================================
# 综合遍历 Cypher
# ================================================================

def traverse_cypher(direction: str, seed_id: int, max_depth: int = 10) -> str:
    """根据方向返回对应的遍历 Cypher。"""
    if direction == BACKWARD_CHAIN:
        return backward_chain_cypher(seed_id, max_depth)
    return forward_chain_cypher(seed_id, max_depth)


def is_rule_expression(value: str) -> bool:
    """判断是否为规则表达式。"""
    return value.strip().startswith(RULE_PREFIX)
