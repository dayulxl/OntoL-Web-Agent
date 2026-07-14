"""LLM 提示词构建 — 分类提示词 / 字段提取提示词 / 完整本体提示词。"""
from business.ontology import load_ontology_types, get_inherited_fields


def fmt_field(f: dict) -> str:
    """格式化一个字段为提示词中的一行。"""
    req = "必填" if f.get("required", "0") == "1" else "可选"
    default = f"，默认值={f.get('default')}" if f.get("default") else ""
    return (
        f"  - {f.get('code','')} ({f.get('name','')}): "
        f"{req}, {f.get('data_type','VARCHAR')}, "
        f"长度={f.get('length','—')}{default} — {f.get('desc','')}"
    )


def build_ontology_prompt() -> str:
    """构建包含所有本体类型定义的完整 LLM 提示词（含语义规范）。"""
    types = load_ontology_types()
    non_root = {tid: td for tid, td in types.items() if tid != "M_ROOT"}

    lines = []
    lines.append("你是一个本体建模专家。请解析文本，识别实体并归类到以下本体类型，填写所有字段。\n")

    # M_ROOT 概览
    root_inherited = get_inherited_fields("M_ROOT") if "M_ROOT" in types else {}
    if root_inherited:
        lines.append(f"# M_ROOT 本体根节点 — {len(root_inherited)} 个基础字段（所有类型继承）\n")
        for f in sorted(root_inherited.values(), key=lambda x: x.get("code", "")):
            lines.append(fmt_field(f))
        lines.append("")

    # 各本体类型 + 完整继承字段
    lines.append("# 本体类型定义\n")
    for tid, tdef in non_root.items():
        lines.append(f"## {tdef.get('name','')} (ont_type={tid}, 类型代码={tdef.get('type_code','')})")
        lines.append(f"描述: {tdef.get('desc','')}")
        all_fields = get_inherited_fields(tid)
        own_fields = [f for f in all_fields.values() if f.get("source_model") == tid]
        inherited_from = [f for f in all_fields.values() if f.get("source_model") != tid]
        lines.append(f"完整字段 ({len(all_fields)} 个归属, {len(inherited_from)} 个继承 + {len(own_fields)} 个归属):")
        for f in sorted(all_fields.values(), key=lambda x: (x.get("source_model", "") == tid, x.get("order", 0), x.get("code", ""))):
            src_tag = "" if f.get("source_model") == tid else f" [继承自 {f.get('source_name','')}]"
            lines.append(fmt_field(f) + src_tag)
        lines.append("")

    # 字段汇总表
    lines.append("# 字段汇总\n")
    lines.append("每个实体需填写的字段 = 该本体类型的完整继承字段列表（含 M_ROOT 基础字段）。\n")
    for tid, tdef in non_root.items():
        all_fields = get_inherited_fields(tid)
        codes = [f.get("code", "") for f in sorted(all_fields.values(), key=lambda x: x.get("code", ""))]
        lines.append(f"{tdef['name']} ({tid}, 共{len(codes)}字段): {', '.join(codes)}")
    lines.append("")

    # 本体类型枚举说明
    lines.append("""# 本体类型（Ontology Types）枚举说明

在解析文本时，请根据实体的核心业务特征，将其归类为以下 7 种本体类型之一。注意：输出 JSON 时，`type` 字段的值必须严格使用以下指定的代码（如 M1、M2 等）：
- **M1 实体 (M_ENTITY)**：描述客观存在的物理对象、数字资产或核心业务概念。例如：设备、传感器、产品、文档、数据表等。
- **M2 行为 (M_ACTION)**：描述主体执行的动作、操作、流程节点或状态变更。例如：启动、校验、清洗、审批、计算等。
- **M3 规则 (M_RULE)**：描述业务逻辑、约束条件、算法策略、触发条件或计算公式。例如：阈值告警规则、权限校验规则、调度策略等。
- **M4 场景 (M_SCENE)**：描述业务发生的上下文、环境、时间段或特定业务模式。例如：夜间巡检、高并发交易、设备离线状态等。
- **M5 主体 (M_SUBJECT)**：描述执行行为的发起者、责任方、参与角色或组织。例如：操作员、系统服务、部门、外部供应商等。
- **M6 异常 (M_EXCEPTION)**：描述偏离正常状态的故障、错误、风险或告警事件。例如：网络超时、数据缺失、设备过热、越权访问等。
- **M7 质量 (M_QUALITY)**：描述衡量业务、数据或系统表现的标准、指标或评估维度。例如：准确率、响应时间、完整性、合规性等。

""")

    # 动态生成输出示例
    example_type = list(non_root.keys())[0] if non_root else None
    example_fields = get_inherited_fields(example_type) if example_type else {}
    example_props_lines = []
    if example_fields:
        for f in sorted(example_fields.values(), key=lambda x: x.get("code", "")):
            code = f.get("code", "")
            name = f.get("name", "")
            dtype = f.get("data_type", "VARCHAR")
            default = f.get("default", "")
            desc = f.get("desc", "")
            val_hint = default if default else (f"示例{name}" if dtype == "0" else "0")
            example_props_lines.append(f'        "{code}": "{val_hint}",  // {name}, {dtype}{", " + desc if desc else ""}')
    example_props_json = "\n".join(example_props_lines) if example_props_lines else '        // (无定义字段)'

    # 语义规范
    lines.append(_SEMANTIC_SPEC)
    lines.append(example_props_json)
    lines.append(_OUTPUT_RULES)
    return "\n".join(lines)


_SEMANTIC_SPEC = """# 语义规范

## 前缀约定

| 序号 | 作用域 | 名称 | 编码前缀 | 格式示例 | 备注 |
|------|--------|------|----------|----------|------|
| 1 | 对象属性 | RDFS语言 | `rdfs:` | 也支持RDFS核心常量，不写前缀 | RDFS语言 |
| 2 | 对象属性 | OWL2 DL语言 | `owl2:` | | OWL2 DL语言为主 |
| 3 | 对象属性 | SWRL语言 | `swrl:` | | SWRL语法 |
| 4 | 对象属性 | SHACL语言 | `sh:` | | |
| 5 | 对象属性 | 规则设定 | `rule:` | `rule:forwardChain`<br>`rule:backwardChain` | 默认就是前链推理 |
| 6 | 对象属性 | 自定义动态函数 | `func:` | `{"id":"图ID","func":"函数名"}` | 不对接大模型，用JSON调用函数实现 |
| 7 | 边属性 | 自定义动作接口 | 边的属性 | `actionType: "inference"`<br>`required: true`<br>`validationType: "Strong"`<br>`ruleId: "phone_format_rule_001"`<br>`func: "validate_phone_format"`<br>`id: "field_B_node_123"`<br>`msg: "详细说明作用"`<br>`synonym: "同义词"`<br>`queryVariant: "错意词"` | actionType (路由标识)：指定执行分支（如 inference 表示走推理机逻辑）。<br>required (阻断控制)：定义校验失败时，是否强制中断当前业务流程。<br>validationType (规则级别)：声明校验的严格程度（如 Strong 强校验（阻断），弱校验Weak（提醒不阻断））。<br>ruleId (规则锚点)：指向图数据库中的"规则本体节点"，用于元数据管理和错误信息溯源。<br>func (执行指令)：直接映射底层要调用的具体函数名，保障执行引擎高效运转。<br>id (数据锚点)：明确当前需要被校验的具体业务数据节点。 |

> ⚠️ **核心约束**：Memgraph 边属性仅支持标量类型（String / Int / Float / Bool / DateTime / Duration / Point / List）。不支持 Map / JSON 嵌套。所有复合语义必须通过「扁平化 key-value」或「独立节点 + 关系」表达。

## RDFS 核心词汇
RDFS（RDF Schema）为 RDF 数据模型提供基础的类型系统和词汇描述能力：
- **rdfs:subClassOf** — 子类关系（A 是 B 的子类型）
- **rdfs:subPropertyOf** — 子属性关系
- **rdfs:domain** — 属性定义域（该属性适用于哪类主体）
- **rdfs:range** — 属性值域（该属性的值属于哪类客体）
- **rdfs:label** — 人类可读标签
- **rdfs:comment** — 注释说明
- **rdfs:type** — 实例类型声明
- **rdfs:Class** — 类
- **rdfs:Property** — 属性

## 关系（predicate）— 使用 OWL2 DL 语义
实体之间的关系遵循 OWL2 DL（Description Logic）标准，所有关系类型使用 `owl2:` 前缀：
- **owl2:subClassOf** — 子类关系（A 是 B 的子类型）
- **owl2:equivalentClass** — 等价类关系
- **owl2:disjointWith** — 互斥关系（A 和 B 不能同时成立）
- **owl2:objectProperty** — 对象属性（A 指向 B 的语义关联）
- **owl2:dataProperty** — 数据属性（A 拥有某个数据值）
- **owl2:sameAs / owl2:differentFrom** — 个体等价/不等价
- **owl2:inverseOf** — 逆关系（A→B 和 B→A 互为逆）
- **owl2:domain / owl2:range** — 定义域的约束

关系 type 优先使用 OWL2 标准词汇（带 owl2: 前缀），如需要自定义，使用驼峰命名（如 hasPart、isLocatedAt）。

## 推理规则（SWRL）
如文本中包含推理规则，用 SWRL（Semantic Web Rule Language）表达，示例：
  - swrl:Antecedent(body) → swrl:Consequent(head)
  - Entity(?x) ^ hasProperty(?x, ?v) ^ swrlb:greaterThan(?v, 100) → HighValue(?x)

## 校验规则（SHACL）
如文本中包含数据校验约束，用 SHACL（Shapes Constraint Language）表达，常用词汇：
  - **sh:property** — 属性约束声明
  - **sh:class** — 节点类型约束
  - **sh:datatype** — 数据类型约束（如 xsd:string、xsd:integer）
  - **sh:minCount / sh:maxCount** — 最小/最大出现次数
  - **sh:pattern** — 正则表达式匹配
  - **sh:in** — 枚举值约束

## 推理规则设定（rule:）
如文本中包含推理方向或策略设定，使用 `rule:` 前缀表达：
  - `rule:forwardChain` — 前链推理（从已知事实推导新结论），**默认模式**
  - `rule:backwardChain` — 后链推理（从目标反向寻找支撑条件）

## 自定义动态函数（func:）
如文本中需要执行自定义计算或处理逻辑，使用 `func:` 前缀表达。不对接大模型，直接通过 JSON 调用底层函数实现：
  - 格式：`{"id": "图节点ID", "func": "函数名"}`
  - 函数参数根据具体业务需求扩展

## 自定义动作接口（边属性）
边属性用于在关系边上附加校验和执行控制信息，使用 Memgraph key-value 形式存储，不支持嵌套 JSON：

| 字段 | 类型 | 说明 |
|------|------|------|
| `actionType` | string | 路由标识，指定执行分支（如 `inference` 表示走推理机逻辑） |
| `required` | boolean | 阻断控制，校验失败时是否强制中断当前业务流程 |
| `validationType` | string | 规则级别，`Strong` 强校验（阻断），`Weak` 弱校验（提醒不阻断） |
| `ruleId` | string | 规则锚点，指向图数据库中的规则本体节点，用于元数据管理和错误信息溯源 |
| `func` | string | 执行指令，直接映射底层要调用的具体函数名，保障执行引擎高效运转 |
| `id` | string | 数据锚点，明确当前需要被校验的具体业务数据节点 |
| `msg` | string | 详细说明该边属性的作用 |
| `synonym` | string | 同义词，用于语义匹配和模糊查询 |
| `queryVariant` | string | 错意词/变体词，用于容错查询 |

示例：
```
actionType: "inference"
required: true
validationType: "Strong"
ruleId: "phone_format_rule_001"
func: "validate_phone_format"
id: "field_B_node_123"
msg: "校验电话号码格式是否符合规范"
synonym: "手机号校验"
queryVariant: "电话验证,号码检查"
```

## 字段填写规则
1. 每个字段尽量从原文中推断填充，无法推断则留空字符串 ""
2. 字段值保持原文语义，不要臆造
3. 日期/时间字段使用 openCypher 标准时间格式（如 LocalDateTime），到秒即可
4. 编码字段使用英文驼峰或下划线命名
5. 置信度字段如未明确指定，默认填 80%

## 输出格式（严格 JSON）
只输出以下 JSON，不得包含任何解释文字：

```json
{
  "entities": [
    {
      "name": "实体名称",
      "ont_type": "M_ENTITY",
      "type_name": "实体",
      "properties": {
"""

_OUTPUT_RULES = """      }
    }
  ],
  "relationships": [
    {
      "type": "关系类型(如 owl2:subClassOf)",
      "start_node_id": "起始节点名称",
      "end_node_id": "目标节点名称",
      "properties": {
        "note": "Memgraph 属性图模型支持在关系上挂载属性，按需填写"
      }
    }
  ]
}
```

## 重要规则
1. 每个实体必须归类到一个 ont_type（从上面定义的本体类型中选择）
2. 每个实体的 properties 中 `type` 字段必须填写 M1~M7 枚举值
3. properties 必须包含该类型的完整继承字段列表，尽量从文本中提取
4. 关系 type 遵循 OWL2 DL 语义规范（带 owl2: 前缀）
5. 如有推理规则，使用 SWRL 格式填入 hasPrecondition 或单独关系
6. 如有校验约束，使用 SHACL 格式
7. 只输出 JSON，不要输出任何解释"""


def build_classify_prompt() -> str:
    """构建分类提示词 — 仅让 LLM 判断实体归类，不涉及字段细节。"""
    types = load_ontology_types()
    non_root = [(tid, td) for tid, td in types.items() if tid != "M_ROOT"]

    lines = [
        "你是一个本体建模专家。请解析文本，识别实体并归类到以下本体类型。",
        "只需返回实体名称和本体类型，不需要填写属性字段。\n",
        "# 本体类型枚举\n",
    ]
    for tid, tdef in non_root:
        lines.append(f"- **{tdef.get('name','')}** (ont_type={tid}, type_code={tdef.get('type_code','')}): {tdef.get('desc','')}")

    lines.append("""
# 输出格式（严格 JSON，只输出此 JSON）
```json
{
  "entities": [
    {"name": "实体名称", "ont_type": "M_ENTITY"}
  ],
  "relationships": [
    {"type": "关系类型", "start_node_id": "起始实体名", "end_node_id": "目标实体名"}
  ]
}
```""")
    return "\n".join(lines)


def build_extract_prompt(ont_type: str) -> str:
    """构建字段提取提示词 — 仅针对单个本体类型，用继承字段完整列表。"""
    t = load_ontology_types().get(ont_type, {})
    fields = get_inherited_fields(ont_type)
    type_name = t.get("name", ont_type)
    type_code = t.get("type_code", "")

    lines = [
        f"你是本体建模专家。请为以下实体提取字段值，该实体类型为 **{type_name}** (ont_type={ont_type}, type_code={type_code})。",
        f"\n# 需填写的字段（共 {len(fields)} 个，含继承字段）\n",
    ]
    for f in sorted(fields.values(), key=lambda x: (x.get("source_model", "") == ont_type, x.get("order", 0), x.get("code", ""))):
        src = f" [继承自 {f['source_name']}]" if f.get("source_model") != ont_type else ""
        lines.append(fmt_field(f) + src)

    lines.append("""
# 输出格式（严格 JSON，只输出此 JSON）
```json
{
  "entities": [
    {
      "name": "实体名称（与输入一致）",
      "ont_type": \"""" + ont_type + """\",
      "properties": {
        "field_code": "从原文提取的值，无法提取则留空"
      }
    }
  ]
}
```

## 规则
1. 每个字段尽量从原文推断，无法提取留空字符串 ""
2. 字段值保持原文语义，不要臆造
3. 置信度字段默认填 "80%"
4. 只输出 JSON，不输出解释""")
    return "\n".join(lines)
