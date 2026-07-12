"""
SWRL → Cypher 转换器
---------------------
将 SWRL 规则（Antecedent → Consequent）转为 Cypher MATCH-WHERE-CREATE 模式。

SWRL 语法:
  swrl:body(?x,?y) → swrl:head(?x,?y)

转换策略:
  1. 解析 antecedent 和 consequent
  2. 将 antecedent 转为 MATCH 模式
  3. 将 consequent 转为 CREATE/SET 动作
"""

from typing import Tuple

SWRL_PREFIX = "swrl:"


# ================================================================
# 解析 SWRL 表达式
# ================================================================

def parse_swrl(expression: str) -> dict:
    """
    解析 SWRL 表达式:
      "swrl:Antecedent(?x,?y) → swrl:Consequent(?x,?y)"
    返回:
      {"antecedent": "Antecedent(?x,?y)", "consequent": "Consequent(?x,?y)"}
    """
    v = expression.strip()
    parts = v.split("→")
    ant = parts[0].replace(SWRL_PREFIX, "").strip() if parts else ""
    con = parts[1].replace(SWRL_PREFIX, "").strip() if len(parts) > 1 else ""
    return {"antecedent": ant, "consequent": con}


def _extract_predicate_and_args(expr: str) -> Tuple[str, list[str]]:
    """
    从 "hasEnemy(?x,?y)" 提取 ("hasEnemy", ["?x", "?y"])
    从 "hasProperty(x,y)" 提取 ("hasProperty", ["x", "y"])
    """
    import re
    match = re.match(r'^(\w+)\((.*)\)$', expr.strip())
    if not match:
        return expr.strip(), []
    pred = match.group(1)
    args_raw = match.group(2)
    args = [a.strip() for a in args_raw.split(",") if a.strip()]
    return pred, args


# ================================================================
# 单 antecedent → Cypher MATCH
# ================================================================

def antecedent_to_match(antecedent: str, node_var: str = "n") -> str:
    """
    将 SWRL antecedent 转 Cypher MATCH 子句。

    示例:
      "hasEnemy(?x,?y)" → "(n)-[:hasEnemy]->(enemy)"
      "hasStatus(?x,active)" → "(n {status: 'active'})"
    """
    pred, args = _extract_predicate_and_args(antecedent)
    if not args:
        # 无参数 = 属性检查
        return f"({node_var}.{pred} IS NOT NULL)"

    # 判断是属性检查还是关系检查
    if len(args) >= 2 and "?" in args[0] and "?" in args[1]:
        # 关系模式: pred(?x,?y)
        return f"({node_var})-[:`{pred}`]->(tgt)"
    elif len(args) == 2 and "?" not in args[1]:
        # 属性值模式: pred(?x, value)
        return f"({node_var}.{pred} = '{args[1]}')"

    return f"({node_var}.{pred} IS NOT NULL)"


# ================================================================
# 完整 SWRL → Cypher
# ================================================================

def swrl_to_cypher(expression: str, node_var: str = "n") -> str:
    """
    完整 SWRL 规则 → Cypher 语句。

    swrl:hasEnemy(?x,?y) → swrl:alert(?x,?y)
    ↓
    MATCH (n)-[:hasEnemy]->(enemy)
    CREATE (n)-[:alert {derived_from: 'swrl'}]->(enemy)
    """
    parsed = parse_swrl(expression)
    ant_pred, ant_args = _extract_predicate_and_args(parsed["antecedent"])
    con_pred, con_args = _extract_predicate_and_args(parsed["consequent"])

    match_clause = ""
    if len(ant_args) >= 2:
        match_clause = f"MATCH ({node_var})-[:`{ant_pred}`]->(tgt)"
    else:
        match_clause = f"MATCH ({node_var} {{{ant_pred}: TRUE}})"

    create_clause = ""
    if len(con_args) >= 2:
        create_clause = f"CREATE ({node_var})-[:`{con_pred}` {{derived_from: 'swrl'}}]->(tgt)"
    else:
        create_clause = f"SET {node_var}.{con_pred} = TRUE"

    return f"""
    {match_clause}
    {create_clause}
    RETURN {node_var}, tgt
    """


def is_swrl_expression(value: str) -> bool:
    """判断是否为 SWRL 表达式。"""
    return value.strip().startswith(SWRL_PREFIX)
