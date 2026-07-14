"""
规则定义
-------
纯 Python 类/字典定义推理规则。
规则类型：前置条件、效果、成本、时长、优先级、组合执行、置信度传播。

前缀路由规则：
  swrl:  → SWRL 引擎   (antecedent → consequent)
  sh:    → SHACL 引擎  (property/class/datatype 约束)
  owl2:  → OWL2 引擎   (subClassOf/equivalentClass 等语义)
  rule:  → 推理方向   (forwardChain/backwardChain)
  func:  → 动态函数   (JSON 调用)
  $.     → JSONPath   (RFC 9535)
"""

import json as _json
import re as _re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

# ---- 枚举 ----

class RuleVerdict(Enum):
    PASS = "pass"        # 条件满足
    BLOCK = "block"      # 条件不满足，阻断
    SKIP = "skip"        # 条件不存在，跳过

class ValidationLevel(Enum):
    STRONG = "Strong"    # 强校验：不满足就阻断
    WEAK = "Weak"        # 弱校验：不满足提醒但不阻断

# ---- 前缀常量 ----

PREFIX_SWRL = "swrl:"
PREFIX_SHACL = "sh:"
PREFIX_OWL2 = "owl2:"
PREFIX_RULE = "rule:"
PREFIX_RDFS = "rdfs:"
PREFIX_FUNC = "func:"
PREFIX_JSONPATH = "$."

# ---- 规则定义 ----

@dataclass
class Rule:
    """单条推理规则。"""
    name: str
    description: str = ""
    enabled: bool = True

    # 前置条件：存节点属性键名，规则匹配时检查该属性值
    precondition_key: str = "precondition"

    # 效果：存节点属性键名，值为 swrl:/sh:/owl2: 前缀表达式
    effect_key: str = "effect"

    # 成本/时长/优先级
    cost_key: str = "cost"
    duration_key: str = "duration"
    priority_key: str = "priority"

    # 组合执行
    composed_of_key: str = "is_composed_of"

    # 置信度：阈值以下阻断
    confidence_threshold: float = 0.5

    # 校验级别
    validation_level: ValidationLevel = ValidationLevel.STRONG


# ---- 预置规则 ----

DEFAULT_RULE = Rule(
    name="默认前链推理",
    description="沿 actionType=inference 边执行前链推理，检查前置条件、触发效果、记录消耗",
)

STRONG_VALIDATION_RULE = Rule(
    name="强校验推理",
    description="前置条件不满足时阻断推理链，不继续下游",
    validation_level=ValidationLevel.STRONG,
)

WEAK_VALIDATION_RULE = Rule(
    name="弱校验推理",
    description="前置条件不满足时提醒但继续推理",
    validation_level=ValidationLevel.WEAK,
)

BACKWARD_CHAIN_RULE = Rule(
    name="后链推理",
    description="从目标节点反向寻找支撑条件，rule:backwardChain",
)

# ---- 规则注册表 ----

@dataclass
class RuleRegistry:
    """规则注册中心。"""

    rules: dict[str, Rule] = field(default_factory=dict)

    def register(self, rule: Rule) -> None:
        self.rules[rule.name] = rule

    def get(self, name: str) -> Optional[Rule]:
        return self.rules.get(name)

    def get_enabled(self) -> list[Rule]:
        return [r for r in self.rules.values() if r.enabled]

    @classmethod
    def with_defaults(cls) -> "RuleRegistry":
        reg = cls()
        for r in [DEFAULT_RULE, STRONG_VALIDATION_RULE, WEAK_VALIDATION_RULE, BACKWARD_CHAIN_RULE]:
            reg.register(r)
        return reg


# ---- 效果路由 ----

def classify_effect(value: str) -> str:
    """
    根据前缀判断效果类型。
    Returns: "swrl" | "shacl" | "owl2" | "rule" | "rdfs" | "func" | "jsonpath" | "unknown"
    """
    v = value.strip()
    if v.startswith(PREFIX_SWRL):
        return "swrl"
    if v.startswith(PREFIX_SHACL):
        return "shacl"
    if v.startswith(PREFIX_OWL2):
        return "owl2"
    if v.startswith(PREFIX_RULE):
        return "rule"
    if v.startswith(PREFIX_RDFS):
        return "rdfs"
    if v.startswith(PREFIX_FUNC):
        return "func"
    if v.startswith(PREFIX_JSONPATH):
        return "jsonpath"
    return "unknown"


def parse_swrl_effect(value: str) -> dict:
    """
    解析 SWRL 格式: swrl:Antecedent(?x,?y) → swrl:Consequent(?x,?y)
    返回 {"antecedent": "...", "consequent": "..."}
    """
    v = value.strip()
    # 去掉 swrl: 前缀
    parts = v.split("→")
    ant = parts[0].replace(PREFIX_SWRL, "").strip() if parts else ""
    con = parts[1].replace(PREFIX_SWRL, "").strip() if len(parts) > 1 else ""
    return {"antecedent": ant, "consequent": con}


def parse_rule_direction(value: str) -> str:
    """
    解析推理方向: rule:forwardChain / rule:backwardChain
    """
    v = value.strip().replace(PREFIX_RULE, "")
    return v


def parse_func(value: str) -> dict:
    """
    解析动态函数: func:{"id":"图ID","func":"函数名"}
    """
    v = value.strip()
    # 去掉 func: 前缀
    json_str = v[len(PREFIX_FUNC):] if v.startswith(PREFIX_FUNC) else v
    try:
        return _json.loads(json_str)
    except _json.JSONDecodeError:
        return {"raw": json_str}


# ---- 前置条件校验 ----

def check_precondition(props: dict, precondition_key: str) -> RuleVerdict:
    """
    宽容执行：节点有 precondition 就校验，没有就 SKIP。

    支持格式：
      - "status = active"  → 检查 props["status"] == "active"
      - "confidence > 0.5" → 检查 props["confidence"] > 0.5
      - "hasProperty:name" → 检查 "name" in props
    """
    raw = props.get(precondition_key)
    if raw is None:
        return RuleVerdict.SKIP

    raw_str = str(raw).strip()

    # pattern: key = value
    eq_match = _re.match(r'^(\w+)\s*=\s*(.+)$', raw_str)
    if eq_match:
        key, expected_val = eq_match.group(1), eq_match.group(2).strip()
        actual = props.get(key)
        # 类型宽容：尝试数字比较
        if actual is None:
            return RuleVerdict.BLOCK
        if str(actual).strip() == expected_val:
            return RuleVerdict.PASS
        return RuleVerdict.BLOCK

    # pattern: key > number
    gt_match = _re.match(r'^(\w+)\s*>\s*([0-9.]+)$', raw_str)
    if gt_match:
        key, threshold = gt_match.group(1), float(gt_match.group(2))
        actual = props.get(key)
        if actual is None:
            return RuleVerdict.BLOCK
        try:
            if float(actual) > threshold:
                return RuleVerdict.PASS
        except (ValueError, TypeError):
            pass
        return RuleVerdict.BLOCK

    # pattern: key < number
    lt_match = _re.match(r'^(\w+)\s*<\s*([0-9.]+)$', raw_str)
    if lt_match:
        key, threshold = lt_match.group(1), float(lt_match.group(2))
        actual = props.get(key)
        if actual is None:
            return RuleVerdict.BLOCK
        try:
            if float(actual) < threshold:
                return RuleVerdict.PASS
        except (ValueError, TypeError):
            pass
        return RuleVerdict.BLOCK

    # pattern: hasProperty:key
    has_match = _re.match(r'^hasProperty:(\w+)$', raw_str)
    if has_match:
        key = has_match.group(1)
        return RuleVerdict.PASS if key in props else RuleVerdict.BLOCK

    # 兜底：非空即为通过
    return RuleVerdict.PASS if raw_str else RuleVerdict.BLOCK


# ---- 置信度传播 ----

def propagate_confidence(current: float, node_props: dict, threshold: float) -> tuple[float, bool]:
    """
    置信度传播：节点有 confidence 属性就相乘，低于阈值返回 blocked=True。

    Returns: (新置信度, 是否阻断)
    """
    node_conf = node_props.get("confidence")
    if node_conf is not None:
        try:
            current *= float(node_conf)
        except (ValueError, TypeError):
            pass
    blocked = current < threshold
    return current, blocked
