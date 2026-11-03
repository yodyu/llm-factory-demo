# Web 真实模型运行指南

需要 Linux、Python 3.12（含 venv）和已启动的 Docker。以下命令在源码根目录、同一终端执行；所有依赖放在 `.venv`。无 Docker 时可运行单元测试，不能执行生成代码。

## 1 安装部署

```sh
make setup
export PYTHONPATH=src:.
make test
```

缺少 Docker 镜像或 Neo4j 配置时，相关集成用例会跳过，不能计作通过。无需 API Key 的流程体验见[无密钥演示运行指南](no-key-demo.md)。

默认直接执行 `docker`；需要 sudo 的环境先设置 `export FACTORY_DOCKER_COMMAND='sudo -n docker'`。`requirements.txt` 使用固定版本锁文件，包含 Web 和测试依赖。

## 2 环境初始化

真实模式需要模型接口，会产生费用；失败不会自动切换 Mock。按以下步骤配置后可直接创建任务。

### 2.1 模型配置

将私有配置保存在仓库外：

```sh
export FACTORY_PRIVATE="$HOME/.config/llm-factory"
mkdir -p -m 700 "$FACTORY_PRIVATE"
cp -n configs/models/runtime.example.env "$FACTORY_PRIVATE/model.env"
chmod 600 "$FACTORY_PRIVATE/model.env"
```

编辑 `model.env`，填写：

```dotenv
FACTORY_MODEL_MODE=api
LLM_BASE_URL=https://your-provider.example/v1
LLM_MODEL=your-model-id
LLM_API_KEY=your-api-key
LLM_TRANSPORT=openai
```

`LLM_BASE_URL` 不追加 `/chat/completions`；火山 Ark 原生接口使用 `LLM_TRANSPORT=ark_chat`。不要提交私有配置或密钥。

### 2.2 数据库与沙箱

```sh
make neo4j
export FACTORY_KNOWLEDGE_BACKEND=neo4j
export FACTORY_METRICS_KNOWLEDGE="$FACTORY_PRIVATE/knowledge.json"
.venv/bin/python -m factory metrics-knowledge-init --knowledge "$FACTORY_METRICS_KNOWLEDGE"
make sandbox
export FACTORY_METRICS_IMAGE="$(cat .runtime/bootstrap/image-id)"
```

`make neo4j` 使用 Docker Compose v2 启动 Community 5.26，等待健康检查，随机生成密码。HTTP/Bolt 仅绑定 `127.0.0.1:7475/7688`；可用 `FACTORY_NEO4J_HTTP_PORT/FACTORY_NEO4J_BOLT_PORT` 覆盖。密码位于仓库外 `~/.config/llm-factory/neo4j-auth`，权限 0600，数据在独立命名卷中。`FACTORY_SECRET_DIR` 可配置其他仓库外目录；使用该选项时同步修改本节配置路径。

已有数据库不必重新启动实例。按以下格式创建 `knowledge.json`，`auth_file` 内容为 `用户名/密码`，两个文件权限均为 0600，再执行初始化命令：

```json
{"uri":"bolt://127.0.0.1:7688","database":"neo4j","namespace":"factory-demo","auth_file":"/absolute/private/path/neo4j-auth"}
```

初始化需要 schema 与 namespace 读写权限。知识后端由启动环境选择，不是页面选项；Neo4j 连接失败不会自动切换本地 SQLite。沙箱使用非 root、禁网、只读根目录和资源限制，不挂载凭据或 Docker socket。

### 2.3 导入材料

```sh
export FACTORY_METRICS_STATE="$(pwd -P)/.runtime/poc"
export FACTORY_METRICS_MODEL_ENV="$FACTORY_PRIVATE/model.env"
export FACTORY_METRICS_CAMPAIGN="$FACTORY_PRIVATE/campaign.sqlite"
.venv/bin/python -m factory metrics-ingest \
  --state "$FACTORY_METRICS_STATE" --mode api \
  --campaign "$FACTORY_METRICS_CAMPAIGN" --env-file "$FACTORY_METRICS_MODEL_ENV" \
  --knowledge "$FACTORY_METRICS_KNOWLEDGE" --root materials/metrics \
  --output "$FACTORY_PRIVATE/knowledge-snapshot.json"
```

材料导入调用模型并消耗请求额度；知识库已有材料时可跳过。输出快照不会覆盖同名文件。

## 3 Web页面使用

### 3.1 启动与访问

在完成环境初始化的同一终端执行：

```sh
make web
```

页面监听 [127.0.0.1:8501](http://127.0.0.1:8501/)；服务器部署可通过 SSH 端口转发访问。停止页面按 `Ctrl+C`，新终端需重新设置环境变量。

### 3.2 创建任务

先在“系统配置”中确认模型模式与请求额度，再进入“创建任务”，选择以下任一方式。

#### 3.2.1 直接使用示例数据

1. 不上传附件，在需求中输入“用模拟数据检测 CPU 超过 90%，连续三点报警”。系统会使用内置模拟数据。
2. 点击“理解需求”，核对检测指标、阈值和连续点数。
3. 点击“生成并验证”，完成后进入“任务结果”查看结果。

#### 3.2.2 使用上传的数据与标签

可直接使用仓库中的配套示例：[观测数据 observations.csv](../case-example/metrics/csv-upload/upload-labelled/observations.csv) 与 [异常标签 user-labels.csv](../case-example/metrics/csv-upload/upload-labelled/user-labels.csv)。下载这两个文件后：

1. 上传观测数据和对应的异常标签 CSV。
2. 输入需求，例如“使用上传的 CPU 数据和标签，检测 CPU 超过 90%，连续三点报警”。
3. 点击“理解需求”，核对识别结果与附件信息，再点击“生成并验证”。上传标签用于评价检测效果。

材料导入、需求理解和代码生成共用额度；首次额度为 60 次。额度不足时可在配置页显式授权新一轮，旧调用记录保留；不要删除账本重置历史。切换到 Mock 可体验受控响应，但仍需可用知识库与 Docker。

#### 3.2.3 需求与数据格式

需求写明数据来源、检测指标和告警条件，例如“使用上传数据，CPU 超过 90%，连续三点报警”；连续点数支持 1～3。修改需求、附件或模型配置后，需重新点击“理解需求”。

- **观测数据**：UTF-8 CSV，仅含 `timestamp,host_id,value`，202～50,000 点、文件不超过 16 MiB。单主机单指标，时间为 UTC、唯一、递增且间隔固定；缺失值留空。支持 gauge 或已换算的 rate，单位为 `percent/ms/bytes/s`。
- **异常标签**：单独的 CSV，仅含 `timestamp,host_id,is_anomaly`，标签值为 `0/1` 或 `true/false`，与观测数据的时间、主机精确对齐，完整覆盖第 201 点起的数据。

### 3.3 查看与下载结果

进入“任务结果”，通过以下页签查看本次任务：

| 页签 | 作用 |
| --- | --- |
| 结果概览 | 查看检测曲线、告警事件、最终测试指标及候选方案比较。 |
| 运行与验证 | 查看代码生成与修复过程、工程检查结果及独立模拟基准。 |
| 知识依据 | 查看本次使用的材料、引用片段与来源行号，并可跳转知识图谱追溯。 |
| 模型用量 | 查看本次任务的模型调用记录、请求次数与 token 用量。 |

顶部“下载与原始记录”可下载交付包、报告 JSON、候选源码及原始报告；事件表旁可下载告警事件与逐点数据。交付包可能包含上传的数据与标签，请按数据权限保存和分享。

## 4 验证与故障排查

安装后可运行以下诊断；该命令检查依赖、Docker、镜像、知识库和模型配置，不发起模型请求：

```sh
.venv/bin/python -m factory doctor \
  --image "$FACTORY_METRICS_IMAGE" \
  --knowledge "$FACTORY_METRICS_KNOWLEDGE" \
  --env-file "$FACTORY_METRICS_MODEL_ENV"
```

真实材料导入可能因模型结构化输出或引用依据不满足要求而失败。检查命令结果中的 `status`、各材料的 `source_checked/REJECTED` 和错误记录；中途退出不表示此前所有材料都成功。已注册的专家插件卡片与模型抽取结果分别保留来源，Web 能生成代码也不能反推材料抽取已全部通过。

保留失败任务和额度记录后，可用 `--sources` 单独重试某份材料；每次使用新的输出文件名，仍会产生真实请求：

```sh
.venv/bin/python -m factory metrics-ingest \
  --state "$FACTORY_METRICS_STATE" --mode api \
  --campaign "$FACTORY_METRICS_CAMPAIGN" --env-file "$FACTORY_METRICS_MODEL_ENV" \
  --knowledge "$FACTORY_METRICS_KNOWLEDGE" --root materials/metrics \
  --sources 03-rolling-mad.txt \
  --output "$FACTORY_PRIVATE/knowledge-retry-01.json"
```

模型超时任务可能只有方案草稿，不能当作已生成和验证成功。可保留失败报告，通过页面再次提交为新任务；供应商未返回的 token 用量记为未知。模型失败不会切换 Mock。

修复前服务器实测：安装、基础设施和真实 Web 生成可用，基础测试 488 项通过、71 项跳过；真实全量材料抽取只有 2/8 份通过，原始记录见[环境搭建验证报告](../case-example/metrics/web-verification-20261102/getting-started-report.md)。2026-11-03 修复后，独立命名空间真实重验 8/8 份通过来源与引用校验、498 项测试通过，见[修复与回归报告](../case-example/metrics/web-verification-20261102/bugfix-report.md)。环境检查、材料来源校验与算法实现验证分别判定。

