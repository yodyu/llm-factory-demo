# 冻结示例索引

仅保留用于理解、测试和回放的样例。报告、生成代码、快照和 ZIP 保留原始字节；其中的时间、旧版本标识和运行路径属于历史来源，不能当作当前部署配置或本次测试结果。

| 目录 | 内容 |
| --- | --- |
| [delivery/real-memory-v1](delivery/real-memory-v1/) | 真实 LLM 双候选任务，包含通过与失败版本 |
| [delivery/real-memory-v1.zip](delivery/real-memory-v1.zip) | 闭环验收脚本使用的摘要绑定回放包 |
| [delivery/transfer-memory-v2](delivery/transfer-memory-v2/) | 后续真实生成任务 |
| [delivery/reproduction-v2](delivery/reproduction-v2/) | 故障注入后的历史真实模型修复 |
| [delivery/knowledge-source.json](delivery/knowledge-source.json) | 历史真实材料抽取快照 |
| [submission/normal](submission/normal/) | mock 双候选闭环及报告 |
| [submission/injected-repair](submission/injected-repair/) | mock 故障修复版本轨迹 |
| [submission/extracted-knowledge.json](submission/extracted-knowledge.json) | mock 抽取快照 |
| [submission/published-knowledge.json](submission/published-knowledge.json) | 含实现、验证和经验的回写快照 |
| [csv-upload](csv-upload/) | 模拟、有标签与无标签上传的冻结报告和下载产物 |
| [plugin-ewma-mock](plugin-ewma-mock/) | EWMA 插件的 Mock 多候选验证与知识回写样例 |
| [readme-code-examples](readme-code-examples/) | 历史 README 源码样例及版本清单；当前案例源码见各验证报告 |
| [web-verification-20261102](web-verification-20261102/REPORT.md) | 2026-11-03 四个 Web 模拟场景的最终验证报告、截图与附件清单 |
| [post-fix-regression-20261102](post-fix-regression-20261102/REPORT.md) | 评价目标传递与同名任务切换修复的回归证据，附当次部署记录 |

验证与回归目录保留对应的操作截图、测试输出及部署记录，用于核对当次结论；当前安装和启动步骤以[运行指南](../../docs/getting-started.md)为准。项目结构和复现入口见[README](../../README.md)。
