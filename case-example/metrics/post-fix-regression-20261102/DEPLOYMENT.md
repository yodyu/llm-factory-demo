# 修复部署记录

用户在本轮追加授权“改好后本地提交，部署”。

- 部署：`/path/to/llm-factory/releases/<release>`，`current` 原子切换到新版本；旧版本保留。
- 服务：`llm-factory-metrics.service`，`active/running`，服务器 `127.0.0.1:8501`；本机通过既有 SSH 转发访问。
- 服务配置备份：`.deployment-backups/llm-factory-metrics-before-<release>.service`。新运行环境文件仅更新 PYTHONPATH 和能力目录到新版本，其余配置保持原值，未导出配置内容。
- 复用原依赖的独立 `.venv` 副本，无依赖安装。统一 state 继续为 `.runtime/poc`，未迁移或重建数据库。
- 部署前活动任务数为 0。健康端点返回 `ok`；实际导入 app.py 路径位于新 release。
- 在已部署代码通过主编排选择节点离线重放内存开发指标，输出 `sustained_coverage / ewma_upper_alpha02_persistence2`。
- 正式 Web 复核：同名任务选项包含各自 task_id；选择 ui-ac5fa8e7cab64a6d 后切到知识依据，仍是固定阈值、13 条提供知识/5 条引用。证据见 `deployed-web.txt` 和截图 07、08。
- 真实模型额度仍为 **44/60**，此次修复验证和部署新增模型调用 0；两条问题任务的原报告 SHA-256 与重放前一致，见 `deployment.json`。
- 临时 8502 服务及本轮创建的 SSH 转发已关闭；正式 8501 服务继续运行。隔离回归目录保留以便审查。

回退仅在需要时执行（本次未执行）：将 current 原子切回 releases/<previous-release>，恢复上述 service 备份到用户 systemd 目录，然后 `systemctl --user daemon-reload` 和 `systemctl --user restart llm-factory-metrics.service`。state 与数据库不随代码回退而替换。

限制仍见 REPORT.md：历史错误成绩不重写；没有再次进行真实模型端到端验证，也未为重放新胜者执行最终集。
