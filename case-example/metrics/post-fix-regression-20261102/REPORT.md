# 修复后回归报告（2026-11-02）

P0 评价目标传递、P1 同名任务切换错位均已修复。验证在指定服务器 `/path/to/llm-factory/regression-fixes-20261102` 的独立 `.venv` 完成。本机仅编辑、同步、Git 操作及通过 SSH 转发访问页面。回归时未改写原始 Web 记录，并在服务器通过 SHA-256 核对；后续真实模型重验见 [Web 验证报告](../web-verification-20261102/REPORT.md)。当前公开附件已移除失效提交引用并将个人路径替换为占位路径，校验清单对应脱敏后的文件。

## 根因与最小修改

### P0

`MetricsRequest.evaluation_objective` 和 `MetricsTask.evaluation_objective` 是真实字段；默认均为 `event_detection`。主编排 `task_actions.select_candidate` 没有传该字段，导致 `select_development` 使用默认事件目标。历史重评 `requalification.py` 也遗漏了目标、偏好和门槛参数。

- `src/factory/metrics/orchestration/nodes.py`：显式传冻结任务的 `evaluation_objective`，保留现有偏好、验收门槛和候选预算。
- `src/factory/metrics/requalification.py`：显式传同一组冻结参数；只影响未来显式启动的重评，不重写旧任务。
- `src/factory/metrics/__main__.py`：reference-check 无用户冻结任务，显式记录其既有 `event_detection/balanced` 默认。Web 与常规 CLI 都进入同一主编排。
- `evaluation.py`：说明旧任务缺字段时兼容事件默认，仅内存加载，不回填历史文件。
- `app.py`：候选比较摘要显示实际目标与偏好；最终指标卡按实际选择目标显示点级或事件 F1。指标卡是最终效果摘要，开发排序仍按记录的 F1/F2/F0.5，不用最终分数排序。
- `reports.py`：报告增加与 UI 共用的选优依据投影，主要指标、次级指标和决胜项以 selection.criteria 为准。

未修改资格过滤、业务门槛、确定性决胜、最终测试隔离和算法。未硬编码 EWMA。

### P1

不仅是视觉重名：服务器 Streamlit **1.66.1** 的 `SelectboxSerde.serialize` 会把 Python 路径转换为 `format_func` 标签；`deserialize` 通过 `formatted_option_to_option_index` 查回选项。重复标签覆盖为最后一个索引，故实际浏览器 rerun 可将新任务还原成旧任务。服务器实际复现 `new → same → old`。原有 AppTest 直接写 Python 路径，且未检查浏览器字符串往返，不能检出此缺陷。

`app.py` 的已完成和活动任务标签均包含完整真实 task_id，缺 ID 时使用唯一绝对记录路径；不引入虚构时间。保留绝对报告路径作为 `selected_task` 的持久身份，与短生命周期 `review_task` 组件状态分开。列表排序、刷新和任务完成均按同一路径关联。只有所选记录不再可用时回退，并显示提示。图谱范围复用相同 task_label；交付包、源码、引用及用量从当前报告目录传入，不另按显示文本查找。

## 自动回归与命令

在服务器 checkout 中执行，所有 Python 命令均用 `.venv/bin/python`，未安装依赖。

```sh
PYTHONPATH=src:. .venv/bin/python -m pytest \
  tests/metrics/test_selection_regression.py tests/metrics/test_navigation.py \
  tests/metrics/test_app.py tests/metrics/test_result_presentation.py \
  tests/metrics/test_ui_presentation.py tests/metrics/test_requirements.py \
  tests/metrics/test_orchestration.py -q
```

最终统一结果 **111 passed、10 skipped**，见 `pytest-final-confirmed.txt`。初轮 69 passed；扩展轮 109 passed、10 skipped。新增指标卡测试最初缺少“已选择候选”前提，显示保守占位符；补齐测试输入后展示文件 11 passed，保留中间失败日志供审计。

额外完整图执行使用现有完整镜像 ID 和 mock 模型：

```sh
image_id=$(sudo -n docker image inspect llm-factory-metrics-sandbox:latest --format '{{.Id}}')
FACTORY_DOCKER_COMMAND='sudo -n docker' FACTORY_METRICS_IMAGE="$image_id" \
PYTHONPATH=src:. .venv/bin/python -m pytest \
  tests/metrics/test_orchestration.py::test_repair_is_executed_by_graph_and_evidence_is_digest_bound -q
```

实际 **1 passed**，见 `pytest-mock-graph-pinned.txt`。首次使用镜像 tag 被项目“必须完整镜像 ID”约束拒绝，日志亦保留。该检查为 mock 编排/沙箱验证，不是真实模型端到端验证。

新增测试覆盖：

- A 事件质量更好、B 点级质量更好，两目标 × balanced/recall/precision 均经过真实编排选择适配器，验证目标、排序、决胜项及报告/UI 依据一致。
- 偏好变化时 Fβ 实际排名变化；旧任务默认不修改原始字典。
- 同标题同数据集两记录，经真实 SelectboxSerde 字符串往返能还原各自路径；四栏目多轮切换，检查候选、selection、引用和模型操作均来自所选报告。
- 列表排序改变、活动任务转完成后保持身份；原有导航、下载入口及图谱范围回归继续通过。

## 历史开发集离线重放

```sh
PYTHONPATH=src:. .venv/bin/python case-example/metrics/post-fix-regression-20261102/replay.py \
  --source-state /path/to/llm-factory/.runtime/poc \
  --web-state .runtime/web-regression \
  --output case-example/metrics/post-fix-regression-20261102/replay.json
```

[replay.json](replay.json) 明确标记 `post_fix_development_replay`，仅把原候选开发指标送入实际编排选择节点。模型调用 0，最终测试执行 false，原报告字节核对不变。

| 任务 | 冻结目标 / 偏好 | 原选择 | 修复后重放 | 实际主排序 |
| --- | --- | --- | --- | --- |
| ui-b0c4acdd29bc47d9 | sustained_coverage / recall | 固定阈值 | EWMA alpha 0.2 | point_fbeta，β=2 |
| ui-a25079152c7940fa | sustained_coverage / precision | EWMA alpha 0.3 | EWMA alpha 0.3 | point_fbeta，β=0.5 |

原最终成绩和原 selection 原样保留；重放没有为新胜者执行最终集，不声称 EWMA 的新最终成绩。

## 真实 Web 复核

隔离服务在服务器 `127.0.0.1:8502`，本机同端口仅作 SSH 转发。历史记录复制到独立 state，未配置真实模型，未重新生成任务。通过实际浏览器操作完成：

| task_id | 四栏目保持的内容 |
| --- | --- |
| ui-ac5fa8e7cab64a6d | 固定阈值 cpu_upper_90_p3；1 候选/1 版本；知识提供13/引用5；工作流请求2、token 34,735；事件F1 0.8 |
| ui-39b59545cd5d4b96 | 固定阈值 cpu_gt90_p3，另含 MAD；2 候选/2 版本；独立引用材料含MAD；工作流请求3、token 96,495；事件F1 0.8 |

两任务分别连续切换概览、运行与验证、知识依据、模型用量；旧任务在隔离副本 mtime 改变导致列表重排后仍保持原身份。打开图谱后查看范围仍为 ui-39b59545cd5d4b96。真实 DOM 证据见 [web-checks.json](web-checks.json)。

截图：

- [01 同名可区分](screenshots/01-distinct-tasks.jpg)
- [02 新 CPU 概览](screenshots/02-cpu-overview.jpg)
- [03 同一新 CPU 知识依据](screenshots/03-cpu-knowledge.jpg)
- [04 同一新 CPU 用量](screenshots/04-cpu-usage.jpg)
- [05 旧 CPU 知识依据](screenshots/05-old-cpu-knowledge.jpg)
- [06 旧 CPU 用量](screenshots/06-old-cpu-usage.jpg)

## 限制

- 本次是修复回归、历史开发指标重放和历史页面复核，不是新一轮真实模型端到端验证。
- 活动任务转完成通过状态/页面测试验证，没有为此消耗真实模型额度。
- 隔离 Web 未配置实时 Neo4j，回写核验和实时图谱明确报配置不可用；只验证任务范围和冻结证据身份，不宣称实时数据库再验收。
- 统一回归的10项环境依赖测试跳过；其中一项完整编排另以固定镜像运行通过，其他跳过项未据此视为通过。
- 旧任务原有目标与 selection 不一致的证据继续可见，不静默修改历史成绩。部署记录另存 DEPLOYMENT.md。
