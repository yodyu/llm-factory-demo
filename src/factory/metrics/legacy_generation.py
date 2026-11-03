# Compatibility only for frozen metrics-knowledge/1 and deprecated typed callers.
"""Standalone algorithm generation and bounded repair from development differences only."""

from contracts.metrics_knowledge import GeneratedCode

INTERFACE = '''
只返回独立 Python 算法源码，不能导入 factory、execution、参考实现、其他本地文件或外部依赖。
批准导入仅 math, statistics, collections, json, datetime, typing, bisect, __future__。
def create_detector(config: dict) 返回检测器，有以下方法：
fit(train_points: list[dict])：原始训练点含 timestamp,host_id,value（可为None）。
reset()：恢复拟合后的统计量并清空本角色历史。
score_one(point: dict) -> dict：当前点含 timestamp,host_id,value,original_present,imputation,missing_streak。
save_state() -> str：最多128KiB JSON对象文本。load_state(raw: str) 恢复相同分数状态。
输出恰好 timestamp,host_id,status,score,evidence；status=ok/insufficient_history/missing_input/invalid_input。
ok 时 score 为有限数；非 ok 时必须为None。timestamp/host_id 与当前点相同。
evidence 始终是字典，非ok时使用空字典{}，不可为None或列表；值仅允许有限数、字符串或None。
可信侧完成缺失处理、校准、告警连续点及事件合并，源码不要产生标签或 is_anomaly。
fixed_threshold：upper=x-T，lower=T-x，evidence包含threshold；缺失value时missing_input。
rolling_mad：仅使用当前点前最近window时间槽（包含None槽）；只有original_present=True的历史点计min_history。
可用插补值可参与median/MAD，但不计真实历史数。value=None时missing_input；真实历史不足时insufficient_history。
m=median(有效历史)，mad=median(abs(v-m))，s=max(1.4826*mad,scale_floor)。
upper=(x-m)/s，lower=(m-x)/s，two_sided=abs(x-m)/s。evidence含median,mad,scale。
训练有效原始值R7分位数（位置(n-1)*q线性插值）的IQR确定scale_floor=max(1e-9,IQR*1e-6)。
先评分，再把当前点追加到历史；包括异常点、插补和不可用None槽，保留最近window槽。
min_history不足不能因为插补提前结束冷启动。fit不能把训练点留作角色滚动历史。
模型源码不得读文件、访问网络、执行动态代码、调用子进程、打印协议输出或进行任何业务效果评估。
knowledge_ids 仅可引用本次实际提供的知识ID；无知识时为[]。
'''


async def generate(gateway, task, candidate, context, *, version, previous=None, feedback=None):
    from factory.metrics.experience_context import candidate_context
    context = candidate_context(context, candidate.config.method_id)
    public = {"task": context, "frozen_plan": candidate.model_dump(mode="json"), "version": version}
    if previous is not None:
        public.update({"previous_source": previous, "development_feedback": feedback,
                       "allowed_changes": "candidate source only; frozen parameters and evaluation remain unchanged"})
    result = await gateway.ask(task.task_id, f"code-{candidate.candidate_id}-v{version}", GeneratedCode, public,
                               INTERFACE + ("根据具体开发反例修复源码，不得更改冻结参数。" if previous is not None else "实现所选方法。"))
    allowed = set(context["knowledge"]["knowledge_ids"])
    unknown = sorted(set(result.knowledge_ids) - allowed)
    if unknown:
        result = result.model_copy(update={"knowledge_ids":[k for k in result.knowledge_ids if k in allowed],
            "explanation": result.explanation + "\n演示纠正：已移除本次未提供的知识引用（不作为依据）：" + ', '.join(unknown)})
    return result
