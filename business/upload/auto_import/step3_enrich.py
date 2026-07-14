"""
Step 3 — 逻辑行为属性填充 & 推理机验证
--------------------------------------
扫描 AI 解析产出的实体/关系，识别 7 种符号语言前缀，
填充标准边属性（actionType/required/validationType/ruleId/func/id/msg/synonym/queryVariant），
并调用转换器进行结构性校验。

7 种符号语言:
  1. RDFS     rdfs:   → rdfs_converter
  2. OWL2 DL  owl2:   → owl2_converter
  3. SWRL     swrl:   → swrl_converter
  4. SHACL    sh:     → shacl_converter
  5. 规则设定  rule:   → rule_converter
  6. 动态函数  func:   → func_converter
  7. JSONPath  $.      → jsonpath_converter

规范参见 CLAUDE.md 中的「本体前缀规范」和「边属性规范」。
"""
from __future__ import annotations

import json as _json
from dataclasses import dataclass, field
from typing import Any


# ═══════════════════════════════════════════════════════════════════════
# 前缀 → 分类名 映射
# ═══════════════════════════════════════════════════════════════════════

PREFIX_MAP: dict[str, str] = {
    "rdfs:": "rdfs",
    "owl2:": "owl2",
    "swrl:": "swrl",
    "sh:":   "shacl",
    "rule:": "rule",
    "func:": "func",
    "$.":    "jsonpath",
}


def classify_prefix(value: str) -> str:
    """识别字符串值的前缀类型，返回分类名或空串。"""
    v = (value or "").strip()
    for prefix, name in PREFIX_MAP.items():
        if v.startswith(prefix):
            return name
    return ""


# ═══════════════════════════════════════════════════════════════════════
# 符号语言 → 边属性默认值
# ═══════════════════════════════════════════════════════════════════════

# 每个已知的符号语言谓词，其对应的标准边属性默认值
SYMBOL_EDGE_PROPS: dict[str, dict[str, str]] = {
    # ── RDFS ──
    "rdfs:subClassOf":     {"actionType": "inference", "required": "true",  "validationType": "Strong", "msg": "RDFS 子类关系"},
    "rdfs:subPropertyOf":  {"actionType": "inference", "required": "false", "validationType": "Weak",   "msg": "RDFS 子属性关系"},
    "rdfs:domain":         {"actionType": "inference", "required": "true",  "validationType": "Strong", "msg": "RDFS 定义域"},
    "rdfs:range":          {"actionType": "inference", "required": "true",  "validationType": "Strong", "msg": "RDFS 值域"},
    "rdfs:label":          {"actionType": "data",      "required": "false", "msg": "RDFS 人类可读标签"},
    "rdfs:comment":        {"actionType": "data",      "required": "false", "msg": "RDFS 注释"},
    "rdfs:seeAlso":        {"actionType": "data",      "required": "false", "msg": "RDFS 参考链接"},
    "rdfs:isDefinedBy":    {"actionType": "data",      "required": "false", "msg": "RDFS 定义来源"},
    "rdfs:type":           {"actionType": "inference", "required": "true",  "validationType": "Strong", "msg": "RDFS 实例类型声明"},
    # ── OWL2 DL ──
    "owl2:subClassOf":     {"actionType": "inference", "required": "true",  "validationType": "Strong", "msg": "OWL2 子类关系"},
    "owl2:equivalentClass":{"actionType": "inference", "required": "false", "validationType": "Weak",   "msg": "OWL2 等价类"},
    "owl2:disjointWith":   {"actionType": "inference", "required": "true",  "validationType": "Strong", "msg": "OWL2 互斥关系"},
    "owl2:objectProperty": {"actionType": "inference", "required": "false", "validationType": "Weak",   "msg": "OWL2 对象属性"},
    "owl2:dataProperty":   {"actionType": "data",      "required": "false", "msg": "OWL2 数据属性"},
    "owl2:sameAs":         {"actionType": "inference", "required": "false", "msg": "OWL2 个体等价"},
    "owl2:differentFrom":  {"actionType": "inference", "required": "true",  "validationType": "Strong", "msg": "OWL2 个体不等价"},
    "owl2:inverseOf":      {"actionType": "inference", "required": "false", "msg": "OWL2 逆关系"},
    "owl2:domain":         {"actionType": "inference", "required": "true",  "validationType": "Strong", "msg": "OWL2 定义域"},
    "owl2:range":          {"actionType": "inference", "required": "true",  "validationType": "Strong", "msg": "OWL2 值域"},
    # ── SWRL ──
    "swrl:":               {"actionType": "inference", "required": "true",  "validationType": "Strong", "ruleId": "swrl_engine",      "msg": "SWRL 推理规则"},
    # ── SHACL ──
    "sh:property":         {"actionType": "inference", "required": "true",  "validationType": "Strong", "msg": "SHACL 属性存在约束"},
    "sh:class":            {"actionType": "inference", "required": "true",  "validationType": "Strong", "msg": "SHACL 节点类型约束"},
    "sh:datatype":         {"actionType": "inference", "required": "true",  "validationType": "Strong", "msg": "SHACL 数据类型约束"},
    "sh:minCount":         {"actionType": "inference", "required": "false", "validationType": "Weak",   "msg": "SHACL 最小出现次数"},
    "sh:maxCount":         {"actionType": "inference", "required": "false", "validationType": "Weak",   "msg": "SHACL 最大出现次数"},
    "sh:pattern":          {"actionType": "inference", "required": "true",  "validationType": "Strong", "msg": "SHACL 正则匹配"},
    "sh:in":               {"actionType": "inference", "required": "true",  "validationType": "Strong", "msg": "SHACL 枚举值约束"},
    "sh:nodeKind":         {"actionType": "inference", "required": "false", "msg": "SHACL 节点类型"},
    "sh:path":             {"actionType": "inference", "required": "false", "msg": "SHACL 属性路径"},
    # ── 规则设定 ──
    "rule:forwardChain":   {"actionType": "inference", "required": "true",  "ruleId": "rule:forwardChain",  "msg": "前链推理 — 从已知事实推导新结论"},
    "rule:backwardChain":  {"actionType": "inference", "required": "true",  "ruleId": "rule:backwardChain", "msg": "后链推理 — 从目标反向寻找支撑条件"},
    # ── 动态函数 ──
    "func:":               {"actionType": "inference", "required": "false", "validationType": "Weak",   "msg": "动态函数调用"},
    # ── JSONPath ──
    "$.":                  {"actionType": "data",      "required": "false", "msg": "JSONPath 属性路径"},
}


def get_edge_props_for_symbol(symbol: str) -> dict[str, str]:
    """根据符号语言谓词返回推荐的标准边属性。

    精确匹配优先 → 前缀匹配兜底。
    """
    s = symbol.strip()
    # 精确匹配
    if s in SYMBOL_EDGE_PROPS:
        return dict(SYMBOL_EDGE_PROPS[s])
    # 前缀匹配兜底（如 "rdfs:xxx" 没在精确列表中）
    for prefix, name in PREFIX_MAP.items():
        if s.startswith(prefix):
            fallback = SYMBOL_EDGE_PROPS.get(prefix, {})
            if fallback:
                return {"actionType": "inference", "ruleId": s, **{k: v for k, v in fallback.items() if k != "ruleId"}}
            return {"actionType": "inference", "ruleId": s, "msg": f"{name.upper()} 符号属性"}
    return {}


# ═══════════════════════════════════════════════════════════════════════
# 校验函数 — 调用各 converter 的解析器做结构性检查
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class ValidationWarning:
    """单条校验告警。"""
    level: str          # "error" | "warn" | "info"
    target: str         # "entity:name" | "relationship:pred" | "property:key"
    message: str


def _validate_swrl(value: str) -> list[ValidationWarning]:
    """校验 SWRL 表达式: antecedent → consequent 结构。"""
    from business.transformation.swrl_converter import parse_swrl, _extract_predicate_and_args
    warnings: list[ValidationWarning] = []
    try:
        parsed = parse_swrl(value)
        if not parsed.get("antecedent") or not parsed.get("consequent"):
            warnings.append(ValidationWarning("error", f"swrl:{value[:60]}", "SWRL 缺少 antecedent 或 consequent"))
        else:
            ant_pred, ant_args = _extract_predicate_and_args(parsed["antecedent"])
            con_pred, con_args = _extract_predicate_and_args(parsed["consequent"])
            if not ant_pred:
                warnings.append(ValidationWarning("warn", f"swrl:{value[:60]}", "SWRL antecedent 无法解析谓词"))
            if not con_pred:
                warnings.append(ValidationWarning("warn", f"swrl:{value[:60]}", "SWRL consequent 无法解析谓词"))
    except Exception as e:
        warnings.append(ValidationWarning("error", f"swrl:{value[:60]}", f"SWRL 解析异常: {e}"))
    return warnings


def _validate_func(value: str) -> list[ValidationWarning]:
    """校验 func 表达式: 合法 JSON 包含 id + func 字段。"""
    from business.transformation.func_converter import parse_func
    warnings: list[ValidationWarning] = []
    try:
        parsed = parse_func(value)
        if "raw" in parsed:
            warnings.append(ValidationWarning("error", f"func:{value[:60]}",
                f"func 表达式不是合法 JSON: {parsed['raw'][:80]}"))
        else:
            if "id" not in parsed:
                warnings.append(ValidationWarning("warn", f"func:{value[:60]}", "func 缺少 id 字段（目标节点ID）"))
            if "func" not in parsed:
                warnings.append(ValidationWarning("warn", f"func:{value[:60]}", "func 缺少 func 字段（函数名）"))
    except Exception as e:
        warnings.append(ValidationWarning("error", f"func:{value[:60]}", f"func 解析异常: {e}"))
    return warnings


def _validate_jsonpath(value: str) -> list[ValidationWarning]:
    """校验 JSONPath 表达式: 合法路径结构。"""
    from business.transformation.jsonpath_converter import parse_jsonpath
    warnings: list[ValidationWarning] = []
    try:
        segs = parse_jsonpath(value)
        if not segs:
            warnings.append(ValidationWarning("warn", f"$.{value[:60]}", "JSONPath 路径为空"))
    except Exception as e:
        warnings.append(ValidationWarning("error", f"$.{value[:60]}", f"JSONPath 解析异常: {e}"))
    return warnings


def _validate_shacl(value: str) -> list[ValidationWarning]:
    """校验 SHACL 约束: 已知的约束类型。"""
    known = {"sh:property", "sh:class", "sh:datatype", "sh:minCount",
             "sh:maxCount", "sh:pattern", "sh:in", "sh:nodeKind", "sh:path"}
    warnings: list[ValidationWarning] = []
    v = value.strip()
    # 取第一个 token
    token = v.split()[0] if v else ""
    if token in known:
        # 语法有效
        pass
    elif token.startswith("sh:"):
        warnings.append(ValidationWarning("warn", value[:60], f"未知的 SHACL 约束类型: {token}"))
    return warnings


def _validate_rule(value: str) -> list[ValidationWarning]:
    """校验 rule 表达式: forwardChain / backwardChain。"""
    from business.transformation.rule_converter import parse_direction
    warnings: list[ValidationWarning] = []
    direction = parse_direction(value)
    if direction not in ("forwardChain", "backwardChain"):
        warnings.append(ValidationWarning("warn", value[:60], f"未知推理方向: {direction}，已按 forwardChain 处理"))
    return warnings


VALIDATORS = {
    "swrl":     _validate_swrl,
    "func":     _validate_func,
    "jsonpath": _validate_jsonpath,
    "shacl":    _validate_shacl,
    "rule":     _validate_rule,
    # rdfs / owl2 不需要额外校验 — 前缀匹配即合法
}


# ═══════════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class EnrichResult:
    """Step 3 产出。"""
    entities: list[dict]
    relationships: list[dict]
    # 统计
    symbol_stats: dict[str, int] = field(default_factory=dict)       # {rdfs: N, owl2: M, ...}
    edge_props_filled: int = 0          # 填充了边属性的关系数
    node_symbols_found: int = 0         # 节点属性中发现符号语言的数量
    # 校验
    warnings: list[ValidationWarning] = field(default_factory=list)
    error_count: int = 0
    warn_count: int = 0


def enrich_entities(entities: list[dict], relationships: list[dict]) -> EnrichResult:
    """Step 3 主函数 — 7 种符号语言识别 → 填充边属性 → 结构校验。

    纯 Python 无副作用，不查库、不调 LLM、不写文件。
    返回 EnrichResult 包含富化后的实体/关系和统计信息。
    """
    result = EnrichResult(entities=entities, relationships=relationships)
    symbol_stats: dict[str, int] = {v: 0 for v in PREFIX_MAP.values()}
    all_warnings: list[ValidationWarning] = []

    # ── 1. 扫描关系谓词（type/predicate），填充标准边属性 ──
    for rel in relationships:
        pred = str(rel.get("type") or rel.get("predicate") or "").strip()
        if not pred:
            continue

        category = classify_prefix(pred)
        if not category:
            continue

        symbol_stats[category] = symbol_stats.get(category, 0) + 1

        # 获取推荐边属性并填充（不覆盖已有值 — 宽容执行）
        defaults = get_edge_props_for_symbol(pred)
        if defaults:
            rel_props = rel.setdefault("properties", {})
            filled_any = False
            for k, v in defaults.items():
                if k not in rel_props or not rel_props.get(k):
                    rel_props[k] = v
                    filled_any = True
            if filled_any:
                result.edge_props_filled += 1

        # 校验
        validator = VALIDATORS.get(category)
        if validator:
            all_warnings.extend(validator(pred))

    # ── 2. 扫描节点属性值，识别符号语言 ──
    key_category_map: dict[str, str] = {
        "precondition": "swrl",     # 前置条件通常为 SWRL 或 SHACL
        "effect":       "swrl",     # 效果通常为 SWRL
        "rule":         "rule",     # 规则方向
        "constraint":   "shacl",    # 约束
        "func_ref":     "func",     # 函数引用
        "json_path":    "jsonpath", # JSON 路径
    }

    for ent in entities:
        props = ent.get("properties") or {}
        for key, value in list(props.items()):
            if not isinstance(value, str) or not value.strip():
                continue
            category = classify_prefix(value)
            if not category:
                # 检查 key 是否为已知的符号属性键
                if key in key_category_map:
                    category = key_category_map[key]
                    symbol_stats[category] = symbol_stats.get(category, 0) + 1
                    result.node_symbols_found += 1
                continue

            symbol_stats[category] = symbol_stats.get(category, 0) + 1
            result.node_symbols_found += 1

            # 校验节点属性中的符号表达式
            validator = VALIDATORS.get(category)
            if validator:
                all_warnings.extend(
                    ValidationWarning(w.level, f"entity:{ent.get('name','?')}.{key}", w.message)
                    for w in validator(value)
                )

    # ── 3. 汇总 ──
    result.symbol_stats = {k: v for k, v in symbol_stats.items() if v > 0}
    result.warnings = all_warnings
    result.error_count = sum(1 for w in all_warnings if w.level == "error")
    result.warn_count = sum(1 for w in all_warnings if w.level == "warn")

    return result
