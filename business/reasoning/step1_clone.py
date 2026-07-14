"""
Step 1 — 复制推理关联对象
-------------------------
克隆初始节点 + OWL2 祖先链 + actionType=inference 下游链 到副本空间。

作为独立模块，通过 Python 函数调用供 engine.py 编排调度。
所有需要克隆的节点都会注入 copy_version 属性，并记录到 cm 映射表。
"""

from typing import AsyncIterator

from business.reasoning.engine import ReasoningEvent
from business.reasoning.graph_ops import (
    get_node,
    clone_node,
    walk_inference_chain,
)
from business.transformation.owl2_converter import climb_subclass_chain


async def step1_clone(
    seed_node_id: int,
    copy_version: str,
    cm: dict[int, tuple[dict, int]],
    ancestors: list[dict],
) -> AsyncIterator[ReasoningEvent]:
    """复制初始节点 + RDFS 祖先链 + 推理下游链 → 副本空间。

    三组克隆对象：
      1a. 沿 owl2:subClassOf 向上爬祖先链（父类→祖父→...→顶层）
      1b. 沿 actionType=inference 边向下爬推理下游链
      1c. 将所有收集到的节点克隆到副本空间，填充 cm 映射表

    克隆顺序：顶层祖先先（reversed）→ 种子 → 下游，
    确保继承链方向正确。

    Args:
        seed_node_id: 初始节点原生 ID（Memgraph int64）
        copy_version: 副本版本号，注入到所有克隆节点
        cm: 克隆映射表 {原生ID: (原生节点dict, 副本ID)}，原地填充
        ancestors: 祖先链列表，原地填充（从近到远：[父, 祖父, ...]）

    Yields:
        ReasoningEvent: 每个克隆操作对应一条 log 事件
    """
    # ── 获取初始节点 ──
    seed_node = await get_node(seed_node_id)
    if seed_node is None:
        raise ValueError(f"Seed node {seed_node_id} not found")

    yield ReasoningEvent(step=1, event="log",
        message=f"  初始节点: {seed_node['props'].get('code', seed_node_id)} (原生ID={seed_node_id})")

    # ── 1a. 爬 OWL2 祖先链 ──
    ancestors.clear()
    ancestors.extend(await climb_subclass_chain(seed_node_id))
    yield ReasoningEvent(
        step=1, event="log",
        message=f"  owl2:subClassOf 祖先链: {len(ancestors)} 层 "
                f"({[a['props'].get('code','?') for a in ancestors]})",
        data={"ancestor_count": len(ancestors)},
    )

    # ── 1b. 爬推理下游链 ──
    downstream: list[dict] = []
    visited_ds: set[int] = set()
    await walk_inference_chain(seed_node_id, downstream, visited_ds)
    yield ReasoningEvent(
        step=1, event="log",
        message=f"  actionType=inference 下游链: {len(downstream)} 个节点",
        data={"downstream_count": len(downstream)},
    )

    # ── 1c. 克隆三组节点：祖先（顶层先）→ 种子 → 下游 ──
    for ancestor in reversed(ancestors):
        new_id = await clone_node(ancestor["id"], copy_version, cm)
        yield ReasoningEvent(step=1, event="log",
            message=f"  克隆祖先: {ancestor['props'].get('code','?')} "
                    f"(原={ancestor['id']} → 副={new_id})")

    seed_copy_id = await clone_node(seed_node_id, copy_version, cm)
    yield ReasoningEvent(step=1, event="log",
        message=f"  克隆种子: {seed_node['props'].get('code','?')} "
                f"(原={seed_node_id} → 副={seed_copy_id})")

    for ds in downstream:
        ds_copy_id = await clone_node(ds["id"], copy_version, cm)
        yield ReasoningEvent(step=1, event="log",
            message=f"  克隆下游: {ds['props'].get('code','?')} "
                    f"(原={ds['id']} → 副={ds_copy_id})")
