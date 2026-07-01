"""
总调度 Agent (MasterAgent)
--------------------------
意图识别 + 子 Agent 调度。先通过意图识别判断用户意图，再分派给对应的业务 Agent 执行。

属于 business/ 顶层——跨域编排 route_planning 和 strike_decision 两个业务域。

调度规则:
  - overall (整体规划)  → RoutePlanningAgent + StrikeDecisionAgent 顺序执行
  - route_planning      → RoutePlanningAgent 单独执行
  - strike_decision     → StrikeDecisionAgent 单独执行
"""
import json
import os
import re
from typing import Optional

from langchain_core.tools import BaseTool

from capabilities.agents.base import BaseAgent
from capabilities.prompts.registry import PromptRegistry

# MasterAgent 所在目录，用于加载调度器提示词
_AGENT_DIR = os.path.dirname(os.path.abspath(__file__))


class MasterAgent(BaseAgent):
    """
    总调度 Agent —— 业务层的入口 Agent。

    工作流程:
      1. 意图识别 — 调用 ReAct Agent 分析用户意图
      2. 解析意图 — 从 Agent 输出中提取 JSON 格式的调度指令
      3. 分派执行 — 根据意图路由到对应的业务域 Agent
      4. 结果聚合 — 返回统一的执行结果

    意图分类:
      - overall:          同时调用航路规划 + 打击决策
      - route_planning:   仅调用航路规划
      - strike_decision:  仅调用打击决策

    提示词:
      优先加载 business/prompts/master.txt；
      若文件缺失则回退到 PromptRegistry 默认值。
    """

    agent_name = "master"

    def __init__(self, model):
        super().__init__(model)
        self._route_agent = None
        self._strike_agent = None

    # ------------------------------------------------------------------
    # BaseAgent 抽象方法实现
    # ------------------------------------------------------------------

    def _get_system_prompt(self) -> str:
        """加载调度器提示词，文件缺失时回退到 PromptRegistry。"""
        prompt_file = os.path.join(_AGENT_DIR, "prompts", "master.txt")
        if os.path.isfile(prompt_file):
            with open(prompt_file, "r", encoding="utf-8") as f:
                return f.read().strip()
        return PromptRegistry.get_agent("master")

    def _get_tools(self) -> list[BaseTool]:
        """意图识别不需要工具 — 纯 NL 分类。"""
        return []

    # ------------------------------------------------------------------
    # 初始化（含子 Agent）
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """初始化自身和全部子 Agent。"""
        await super().initialize()

        if self._route_agent is None:
            from business.route_planning.agent import RoutePlanningAgent

            self._route_agent = RoutePlanningAgent(self.model)
            await self._route_agent.initialize()

        if self._strike_agent is None:
            from business.strike_decision.agent import StrikeDecisionAgent

            self._strike_agent = StrikeDecisionAgent(self.model)
            await self._strike_agent.initialize()

    # ------------------------------------------------------------------
    # 执行 — 意图识别 → 分派 → 聚合
    # ------------------------------------------------------------------

    async def run(
        self,
        user_input: str,
        thread_id: Optional[str] = None,
    ) -> dict:
        """
        执行调度流程:

          1. 意图识别（调用父类 ReAct run）
          2. 解析 JSON 意图
          3. 根据意图分派给子 Agent
          4. 聚合返回结果
        """
        # ── Step 1: 意图识别 ──
        intent_result = await super().run(user_input, thread_id)
        raw_output = intent_result["output"]
        intent_data = self._parse_intent(raw_output)

        intent = intent_data.get("intent", "overall")
        sub_queries = intent_data.get("sub_queries", {})

        # ── Step 2: 分派执行 ──
        results: dict = {
            "agent": self.agent_name,
            "intent": intent,
            "reason": intent_data.get("reason", ""),
        }

        if intent in ("route_planning", "overall"):
            route_query = sub_queries.get("route_planning") or user_input
            results["route_planning"] = await self._route_agent.run(
                route_query, thread_id
            )

        if intent in ("strike_decision", "overall"):
            strike_query = sub_queries.get("strike_decision") or user_input
            results["strike_decision"] = await self._strike_agent.run(
                strike_query, thread_id
            )

        return results

    async def stream(self, user_input: str, thread_id: Optional[str] = None):
        """
        流式执行 — 先完成意图识别，再流式返回各子 Agent 的输出。
        """
        # ── Step 1: 意图识别（同步完成） ──
        intent_result = await super().run(user_input, thread_id)
        intent_data = self._parse_intent(intent_result["output"])
        intent = intent_data.get("intent", "overall")
        sub_queries = intent_data.get("sub_queries", {})

        # 先返回调度元数据
        yield {
            "event": "dispatch",
            "agent": self.agent_name,
            "intent": intent,
            "reason": intent_data.get("reason", ""),
        }

        # ── Step 2: 流式执行子 Agent ──
        if intent in ("route_planning", "overall"):
            route_query = sub_queries.get("route_planning") or user_input
            async for event in self._route_agent.stream(route_query, thread_id):
                yield event

        if intent in ("strike_decision", "overall"):
            strike_query = sub_queries.get("strike_decision") or user_input
            async for event in self._strike_agent.stream(strike_query, thread_id):
                yield event

    # ------------------------------------------------------------------
    # 意图解析
    # ------------------------------------------------------------------

    def _parse_intent(self, raw_output: str) -> dict:
        """
        从 Agent 输出中解析 JSON 意图。

        尝试多种策略：
          1. 直接 json.loads
          2. 提取 ```json ... ``` 代码块
          3. 正则匹配 { ... } JSON 对象
          4. 关键词回退
        """
        raw = raw_output.strip()

        # 策略 1: 直接解析
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # 策略 2: 提取 ```json 代码块
        code_block = re.search(r"```(?:json)?\s*\n?(.*?)```", raw, re.DOTALL)
        if code_block:
            try:
                return json.loads(code_block.group(1).strip())
            except json.JSONDecodeError:
                pass

        # 策略 3: 提取第一个 { ... } JSON 对象
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

        # 策略 4: 关键词回退
        return self._fallback_parse(raw)

    def _fallback_parse(self, raw_output: str) -> dict:
        """
        关键词回退 — 当 JSON 解析全部失败时，根据关键词判断意图。
        """
        # 整体规划关键词
        overall_kw = ["整体", "全面", "综合", "协同", "联合", "同时", "一并", "全部"]
        is_overall = any(kw in raw_output for kw in overall_kw)

        # 航路关键词
        route_kw = ["航路", "航线", "路线", "飞行", "途径点", "导航"]
        has_route = any(kw in raw_output for kw in route_kw)

        # 打击关键词
        strike_kw = ["打击", "攻击", "威胁", "风险", "目标", "决策", "监控", "放行"]
        has_strike = any(kw in raw_output for kw in strike_kw)

        if is_overall or (not has_route and not has_strike):
            intent = "overall"
        elif has_route and not has_strike:
            intent = "route_planning"
        elif has_strike and not has_route:
            intent = "strike_decision"
        else:
            intent = "overall"

        return {"intent": intent, "reason": "关键词回退", "sub_queries": {}}
