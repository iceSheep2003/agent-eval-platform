"""可观测性契约 —— **当前为空**。

原本打算把 `Score` 放在这里（`ScoreWritePort`），实现时发现：Score 是 **Trial 的产物**，
与 Run/Trial 同生命周期，由 execution 的评分引擎写入、execution 的固化流程读取。
拆到 observability 会造成写读两端来回穿模块边界，收益为负。

因此 Score 归 execution（表 `run_score`），observability 只负责 Trace / Span
这类**运行时事实**。等 trace 与 run 的关联打通、需要跨模块读 Score 时再在这里加端口。

按契约生长规则 G3：没有消费方的契约项不进契约层。
"""
