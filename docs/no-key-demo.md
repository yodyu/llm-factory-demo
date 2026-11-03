# 无密钥演示运行指南

需要 Linux、Python 3.12（含 venv）和已启动的 Docker，当前账号需有 Docker 执行权限。首次安装和构建需能获取依赖及基础镜像。以下命令在运行服务器的项目根目录执行，依赖安装到 `.venv`。

```sh
make setup
make demo
```

默认直接执行 `docker`；需要 sudo 时使用：

```sh
FACTORY_DOCKER_COMMAND='sudo -n docker' make demo
```

演示构建沙箱，使用本地 SQLite 知识库和 Mock 响应，完成材料导入、模拟任务、代码验证、评价与知识回写，无需 Neo4j 或 API Key。Mock 复制人工参考实现，只验证流程，不算真实模型生成；Docker 执行与评价仍实际进行。

每次运行创建新的 `demo-output/<本次运行目录>/`，终端打印报告路径，源码与报告位于其中的 `state/runs/`。

如需使用 Web 和真实模型，见 [Web 真实模型运行指南](getting-started.md)。
