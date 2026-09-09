"""内置评估器目录。

只登记「有哪些评估器、什么性质」，**实现不在这个模块**——
确定性评估器的实现属于 execution 的评分引擎，LLM Judge 是可选依赖。
`determinism` 决定它能不能支撑高风险门禁（需求说明 §16.7）。
"""

from __future__ import annotations

from ....contracts.common import Determinism
from .models import EvaluatorSpec

BUILTIN_EVALUATORS: tuple[EvaluatorSpec, ...] = (
    EvaluatorSpec(
        name="answer_exact_match",
        version="1.0.0",
        determinism=Determinism.DETERMINISTIC,
        description="最终答案与期望值完全一致",
    ),
    EvaluatorSpec(
        name="answer_contains",
        version="1.0.0",
        determinism=Determinism.DETERMINISTIC,
        description="最终答案包含指定片段",
    ),
    EvaluatorSpec(
        name="answer_json_schema",
        version="1.0.0",
        determinism=Determinism.DETERMINISTIC,
        description="最终答案符合 JSON Schema",
    ),
    EvaluatorSpec(
        name="tool_name_correctness",
        version="1.0.0",
        determinism=Determinism.DETERMINISTIC,
        description="调用了期望的工具",
    ),
    EvaluatorSpec(
        name="tool_argument_schema",
        version="1.0.0",
        determinism=Determinism.DETERMINISTIC,
        description="工具参数符合 Schema",
    ),
    EvaluatorSpec(
        name="tool_success",
        version="1.0.0",
        determinism=Determinism.DETERMINISTIC,
        description="工具调用没有报错",
    ),
    EvaluatorSpec(
        name="step_efficiency",
        version="1.0.0",
        determinism=Determinism.DETERMINISTIC,
        description="步数不超过预算",
    ),
    EvaluatorSpec(
        name="task_completion",
        version="1.0.0",
        determinism=Determinism.DETERMINISTIC,
        description="轨迹是否完成了任务目标",
    ),
    EvaluatorSpec(
        name="policy_compliance",
        version="1.0.0",
        determinism=Determinism.DETERMINISTIC,
        description="是否违反业务或安全规则",
    ),
    EvaluatorSpec(
        name="llm_judge",
        version="1.0.0",
        determinism=Determinism.PROBABILISTIC,
        description="模型评分（judge 模型与 prompt 版本随结果记录）",
    ),
)

#: 前端策略页用的评估器标识 → 目录名。原型把「确定性匹配」等作为选项，
#: 这里做一次映射，避免前端文案直接当标识用。
EVALUATOR_ALIASES: dict[str, str] = {
    "deterministic_match": "answer_exact_match",
    "trajectory_quality": "task_completion",
    "policy_compliance": "policy_compliance",
    "llm_judge": "llm_judge",
}


def resolve_evaluator(name: str) -> EvaluatorSpec | None:
    resolved = EVALUATOR_ALIASES.get(name, name)
    return next((item for item in BUILTIN_EVALUATORS if item.name == resolved), None)
