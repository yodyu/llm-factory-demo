# 四个经典实验：最终报告目录

验证日期：2026-11-03（北京时间）。四个场景采用真实模型和模拟数据，验证入口为 Web。真实模型为 `doubao-seed-2-1-pro-260915 / ark_chat`。

| 验证目的 | 本轮任务 | 最终报告 |
| --- | --- | --- |
| 单方法生成与验证 | CPU 突升，`ui-3dea5cbfa50d4154` | [CPU](cpu-report.md) |
| 多候选比较与选优 | 内存漂移，`ui-1deabf9ab9634a9a` | [内存](memory-report.md) |
| 经验沉淀与后续引用 | 磁盘延迟，`ui-1a5c876ccd124f53` | [磁盘](disk-report.md) |
| 失败修复与版本追溯 | 内存阶跃，`ui-5f4299d229da4349` | [受控修复](history-repair-report.md) |

## 1. 本轮结果与范围

四个任务均为 `COMPLETED / PUBLISHED`。CPU、内存和磁盘候选均在 v0 工程验证通过；受控修复保留 v0 属性失败和真实模型 v1 通过两版，不计自然错误修复率。内存发布后再提交磁盘，两个本轮内存经验 ID 出现在实际代码生成输入和产物引用中。

| 场景 | 最终点 F1 | 最终事件 F1 | 说明 |
| --- | ---: | ---: | --- |
| CPU | 0.6154 | 0.8000 | 点召回 0.4444，漏检 1 个事件 |
| 内存 | 0.9130 | 1.0000 | 点召回 0.9545，点 FP/FN 为 15/5 |
| 磁盘 | 0.3333 | 1.0000 | 点召回 0.2000，匹配延迟 480 秒 |
| 受控修复 | 0.9916 | 1.0000 | 注入后属性失败，真实模型修复通过 |

数据为模拟序列，保留 `LOW_EVENT_COUNT`，未定义业务门槛。`reference_verified` 指契约、属性和有限参考反例检查通过，不是数学证明。可判定覆盖率 100% 也不表示异常点召回率 100%。

## 2. Web 及独立核验

- [36 张本轮原始页面截图](final-classics-20261103/screenshots/) · [页面操作与截图来源记录](final-classics-20261103/web-observations.json)
- [四份浏览器实际下载报告及 CPU 交付 ZIP](final-classics-20261103/downloads/)
- [独立审计汇总](final-classics-20261103/audit-summary.json) · [指标摘要](final-classics-20261103/results-summary.json)
- [本轮经验链](final-classics-20261103/experience-chain.json) · [只读知识快照](final-classics-20261103/knowledge-after.json)
- [CPU 交付包完整性](final-classics-20261103/cpu-delivery-check.json) · [四个任务的原始报告、源码和检查](final-classics-20261103/runs/)
- [报告校验结果](final-classics-20261103/report-checks.json) · [本轮附件清单](final-classics-20261103/manifest.sha256) · [整个报告目录清单](manifest.sha256)

本轮仅重跑四个经典实验。依赖、沙箱镜像与模型配置复用已验收环境；独立 state 和 Neo4j 命名空间初始没有运行经验，仅导入已来源校验的材料。未重复材料导入、环境安装或全量自动化测试。

第 3 轮通过页面授权 60 次额度，本轮预约并发送 18 次：需求理解 6 次（CPU、内存各含一次格式纠错），四个生成工作流合计 12 次。历史累计从 57 增至 75 次，当前剩余 42 次；没有额外失败任务，注入后的 v0 失败属于修复实验内部的预期检查记录。[任务账本](final-classics-20261103/task-ledger.json) · [请求额度](final-classics-20261103/budget-after.json)。

## 3. 其他专项

其他专项维持其各自验证范围：[环境搭建报告](getting-started-report.md)、[插件机制报告](plugin-report.md)、[代码修复及回归报告](bugfix-report.md)。这些专项中的历史原始记录不作为本轮重新执行的证据。
