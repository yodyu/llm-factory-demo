# 磁盘延迟：本轮经验的后续引用（最终报告）

验证日期：2026-11-03（北京时间）。真实模型 `doubao-seed-2-1-pro-260915 / ark_chat`；工程协议 `metrics-method-check/3`，效果协议 `metrics-evaluation/1`。项目及模型任务均在授权服务器执行，通过 SSH 转发后的 Web 页面输入、确认、提交和下载。

**结论：两个真实候选通过；本轮内存经验进入实际磁盘代码生成输入，并被产物显式引用。** 本篇为该场景唯一保留的最终说明报告。

| 项目 | 本轮实际记录 |
| --- | --- |
| 任务 ID | `ui-1a5c876ccd124f53` |
| 数据 | `sim-disk_peaks-v1`，内置模拟数据 |
| 状态 / 来源 | `COMPLETED / llm_api` |
| 最终采用 | `ewma_alpha0.3_p2_upper` |
| 选优目标 / 策略 | `sustained_coverage / precision` |
| 代码修复次数 | 0 |
| 回写 | `PUBLISHED`，6 个节点 |

## 1. Web 操作与需求确认

1. 打开独立验收页，在系统配置核对真实模型。共享请求账本通过页面授权第 3 轮 60 次，历史调用保留。
2. 进入“创建任务”，不上传 CSV，输入下列原文，点击“理解需求”。
3. 在“任务确认”核对指标、方法、显式参数、连续点数及评价目标，再点击“生成并验证”。
4. 完成后查看“结果概览”的最终指标和候选比较；开发集选优，最终测试不参与选择。
5. 打开“运行与验证”核对版本、来源、协议和检查；在“知识依据”核对引用与发布回执。
6. 下载报告 JSON，在服务器与绑定任务、源码、验证记录和图谱独立核对。

> 用模拟数据检测单主机磁盘 I/O 延迟持续升高，比较 EWMA 和滚动 MAD；EWMA 的 alpha 为 0.3，连续两点异常才报警，尽量减少误报，输出检测代码和验证报告。

![磁盘两个方法、少误报偏好及连续两点](final-classics-20261103/screenshots/20-disk-confirmation.jpg)

![EWMA alpha=0.3 参数来源](final-classics-20261103/screenshots/19-disk-parameters.jpg)

## 2. 候选、版本及工程检查

| 候选版本 | 来源 | 工程结果 | 实际检查记录数 |
| --- | --- | --- | ---: |
| `ewma_alpha0.3_p2_upper` v0 | `llm_api` | 通过 | 10 |
| `rolling_mad_w30_p2_upper` v0 | `llm_api` | 通过 | 12 |

检查数包括不同层的同名检查，不等于独立属性种类数。最终通过版本为 `reference_verified`，表示通过列出的契约、属性和有限反例参考比较，不是数学证明。

开发集以 点级 Fβ 为主要依据，β=0.5；下表列点级指标，完整排序次级条件见冻结选优记录。

| 方法 / 候选 | 末版工程检查 | 开发点 Precision | 开发点 Recall | 开发点 Fβ | 排名 |
| --- | --- | ---: | ---: | ---: | ---: |
| EWMA / `ewma_alpha0.3_p2_upper` | 10 条通过 | 1.0000 | 0.2000 | 0.5556 | 1 |
| 滚动 MAD / `rolling_mad_w30_p2_upper` | 12 条通过 | 0.0000 | 0.0000 | 0.0000 | 2 |

![开发集两候选比较](final-classics-20261103/screenshots/29-disk-comparison.jpg)

![两个真实候选的工程验证](final-classics-20261103/screenshots/30-disk-validation.jpg)

- [EWMA v0 源码](final-classics-20261103/runs/disk/candidate-4e5d989937b55224b97743f8b09a349fda30852848a985bc48edabf7db76c7d0/v0.py)；SHA-256 `sha256:d93c75209cb88f1215463c2e46ca612685cb8d72809ed132ede40f666435235d`。
- [滚动 MAD v0 源码](final-classics-20261103/runs/disk/candidate-a05bcd28138e5ad3e95465fd66a1f2ae84d272980209d06507da6ea1b4f2c1ec/v0.py)；SHA-256 `sha256:32f277df832d5254114da8da607659fcda150ac385c82affbbdeea4845f1918a`。

## 3. 最终测试结果

| 指标 | 采用方案的最终测试结果 |
| --- | ---: |
| 计分点 / 真实事件 | 240 / 2 |
| 点 Precision / Recall / F1 | 1.0000 / 0.2000 / 0.3333 |
| 点 TP / FP / FN / TN | 4 / 0 / 16 / 220 |
| 事件 F1；TP / FP / FN | 1.0000；2 / 0 / 0 |
| 匹配延迟中位数 | 480 秒 |
| 正常误报频次 | 0 次/主机小时 |
| 可判定覆盖率 | 100% |

**覆盖率是可判定点比例，不是异常区间召回率。** 保留 `LOW_EVENT_COUNT`，模拟事件少且未定义业务验收门槛，不据此宣称生产效果达标。

事件匹配成功不表示完整覆盖异常区间。点级召回和匹配延迟仍须单独评估，不以事件 F1 掩盖漏检点。

![磁盘成功页与最终指标](final-classics-20261103/screenshots/28-disk-result.jpg)

## 4. 知识、经验及回写

实际提供知识 14 条、显式引用 13 条；提供经验 2 条、引用 2 条；没有未提供知识引用。算法冻结规格来自专家注册卡片及其引用原文，卡片来源为 `reference`，本次通过实现为 `llm_api`。

独立知识命名空间初始经验数为 0；只复用此前已来源校验的材料，没有复制历史实现或经验，也没有重新执行材料导入。

本轮内存任务 `ui-1deabf9ab9634a9a` 先完成发布，再提交本磁盘任务。核验链为：内存发布节点 → 磁盘检索 → 真实代码生成 prompt → 版本 `knowledge_ids`。

| 来自本轮内存的经验 ID | 提供 / 引用 |
| --- | --- |
| `experience-2c0a28207a7c66ce05eb6cf3c84bd3ebfa387404e12d6d908a70dd3682306e0c` | 已提供 / 已引用 |
| `experience-3946b9860fbae3a78763063b9c7f1c60d4247661f8e13c51854b41060c43a622` | 已提供 / 已引用 |

![实际提供和引用的本轮经验](final-classics-20261103/screenshots/31-disk-knowledge.jpg)

![本轮经验 ID 的页面记录](final-classics-20261103/screenshots/32-disk-experience-ids.jpg)

![磁盘知识回写](final-classics-20261103/screenshots/33-disk-publication.jpg)

经验被提供和引用证明了链路，不是其提升检测效果的因果证据。

## 5. 用量、下载及独立核验

生成工作流记录 3 次真实请求，输入/输出 token 89,862 / 6,451，总计 96,313；实际工作流约 141.01 秒。需求理解另计，共享同一账本；用量不完整时不按零计。

四个任务均通过浏览器实际下载报告，解析后与服务器绑定报告一致。所有源码摘要、父版本、冻结规格、插件文件摘要、能力 → 实现 → 验证关系和发布节点均在服务器独立核验。

- [实际下载报告](final-classics-20261103/downloads/disk-report.json) · [任务审计与真实模型输入摘要](final-classics-20261103/runs/disk/audit.json)
- [服务器完整报告](final-classics-20261103/runs/disk/report.json) · [冻结配置与选优](final-classics-20261103/runs/disk/selection.json)
- [附件校验清单](final-classics-20261103/manifest.sha256) · [报告目录](REPORT.md)
