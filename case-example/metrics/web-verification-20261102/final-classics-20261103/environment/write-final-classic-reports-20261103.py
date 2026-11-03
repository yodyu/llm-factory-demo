import json
from pathlib import Path

root = Path('/path/to/llm-factory/final-classic-web-20261103')
proof = root / 'final-evidence'
reports = root / 'final-reports'
reports.mkdir(exist_ok=True)
prefix = 'final-classics-20261103'
names = {'cpu': 'CPU：单方法生成与验证', 'memory': '内存漂移：三候选比较与选优',
         'disk': '磁盘延迟：本轮经验的后续引用', 'repair': '失败修复与版本追溯：受控故障'}
files = {'cpu': 'cpu-report.md', 'memory': 'memory-report.md',
         'disk': 'disk-report.md', 'repair': 'history-repair-report.md'}
shots = {
    'cpu': [('02-cpu-confirmation.jpg', 'CPU 需求确认、单方法及连续三点'),
            ('09-cpu-result.jpg', '本次 CPU 成功页和漏检提示'),
            ('10-cpu-validation.jpg', '真实模型 v0 与工程检查'),
            ('13-cpu-knowledge.jpg', 'CPU 材料及引用统计'),
            ('14-cpu-publication.jpg', 'CPU 知识回写')],
    'memory': [('07-memory-confirmation.jpg', '内存三候选确认'),
               ('06-memory-parameters.jpg', 'EWMA alpha=0.2 等参数来源'),
               ('23-memory-result.jpg', '本次内存最终测试结果'),
               ('24-memory-comparison.jpg', '开发集三候选比较'),
               ('26-memory-validation.jpg', '三候选首次工程检查均通过'),
               ('27-memory-ewma-checks.jpg', 'EWMA 真实来源及检查'),
               ('22-memory-publication.jpg', '本轮内存经验发布')],
    'disk': [('20-disk-confirmation.jpg', '磁盘两个方法、少误报偏好及连续两点'),
             ('19-disk-parameters.jpg', 'EWMA alpha=0.3 参数来源'),
             ('28-disk-result.jpg', '磁盘成功页与最终指标'),
             ('29-disk-comparison.jpg', '开发集两候选比较'),
             ('30-disk-validation.jpg', '两个真实候选的工程验证'),
             ('31-disk-knowledge.jpg', '实际提供和引用的本轮经验'),
             ('32-disk-experience-ids.jpg', '本轮经验 ID 的页面记录'),
             ('33-disk-publication.jpg', '磁盘知识回写')],
    'repair': [('04-repair-confirmation.jpg', '故障注入告知、阈值和连续两点确认'),
               ('11-repair-result.jpg', '完成状态保留故障注入来源'),
               ('12-repair-v0-failure.jpg', 'v0 故障来源与失败版本'),
               ('15-repair-failed-check.jpg', '严格边界属性检查失败'),
               ('16-repair-v1-parent.jpg', '真实模型 v1、父版本及检查通过'),
               ('17-repair-publication.jpg', '失败与修复两版的知识回写'),
               ('18-repair-usage.jpg', '真实修复请求用量')],
}
method_names = {'fixed_threshold': '固定阈值', 'rolling_mad': '滚动 MAD', 'ewma': 'EWMA'}

def load(path):
    return json.loads(path.read_text())

def fmt(value):
    return '未定义' if value is None else f'{value:.4f}'

def metric(group, key):
    return (group.get(key) or {}).get('value')

def fig(label, index):
    file, title = shots[label][index]
    return f'![{title}]({prefix}/screenshots/{file})\n'

records = {label: load(proof / 'runs' / label / 'audit.json') for label in files}
summary = {}
for label, r in records.items():
    final, selection = r['final'], r['selection']
    point, event = final['point'], final['event']
    usage, knowledge = r['usage'], r['knowledge_usage']
    source_links, version_rows, candidate_rows = [], [], []
    repairs = sum(len(c['versions']) - 1 for c in r['candidates'])
    for c in r['candidates']:
        last = c['versions'][-1]
        dev = c['development'] or {}
        dp = dev.get('point') or {}
        beta = selection.get('beta', 1)
        tp, fp, fn = [dp.get(k, 0) for k in ['tp', 'fp', 'fn']]
        denominator = (1 + beta * beta) * tp + beta * beta * fn + fp
        fbeta = ((1 + beta * beta) * tp / denominator) if denominator else None
        rank = selection['ranking'].index(c['candidate_id']) + 1
        candidate_rows.append(f"| {method_names[c['config']['method_id']]} / `{c['candidate_id']}` | "
                              f"{len(last['validation']['checks'])} 条通过 | {fmt(metric(dp, 'precision'))} | "
                              f"{fmt(metric(dp, 'recall'))} | {fmt(fbeta)} | {rank} |")
        for v in c['versions']:
            link = f"{prefix}/runs/{label}/{v['source_path']}"
            source_links.append(f"- [{method_names[c['config']['method_id']]} v{v['version']} 源码]({link})；SHA-256 `{v['source_sha256']}`。")
            version_rows.append(f"| `{c['candidate_id']}` v{v['version']} | `{v['origin']}` | "
                                f"{'通过' if v['passed'] else '未通过'} | {len(v['validation']['checks'])} |")
    statement = {
        'cpu': '单方法真实生成、Docker 工程检查、最终评价、知识回写及浏览器下载核验通过。',
        'memory': '三种方法均首次工程检查通过，按有标签开发集选优，再对 EWMA 执行最终测试。',
        'disk': '两个真实候选通过；本轮内存经验进入实际磁盘代码生成输入，并被产物显式引用。',
        'repair': '受控 v0 故障被检查拒绝，真实模型按反馈生成 v1 并通过复验；父版本关联和知识回写通过。',
    }[label]
    text = f"""# {names[label]}（最终报告）

验证日期：2026-11-03（北京时间）。执行归档与交付源码的 116 个源码、脚本、插件和材料文件逐字一致，以文件 SHA-256 和[源码比对记录](final-classics-20261103/environment/current-source-comparison.json)定位基线。真实模型 `doubao-seed-2-1-pro-260915 / ark_chat`；工程协议 `metrics-method-check/3`，效果协议 `metrics-evaluation/1`。项目及模型任务均在授权服务器执行，通过 SSH 转发后的 Web 页面输入、确认、提交和下载。

**结论：{statement}** 本篇为该场景唯一保留的最终说明报告。

| 项目 | 本轮实际记录 |
| --- | --- |
| 任务 ID | `{r['task_id']}` |
| 数据 | `{r['task']['dataset_id']}`，内置模拟数据 |
| 状态 / 来源 | `{r['status']} / {r['origin']}` |
| 最终采用 | `{selection['selected']}` |
| 选优目标 / 策略 | `{selection['objective']} / {selection['policy']}` |
| 代码修复次数 | {repairs} |
| 回写 | `PUBLISHED`，{len(r['publication']['node_ids'])} 个节点 |

## 1. Web 操作与需求确认

1. 打开独立验收页，在系统配置核对真实模型。共享请求账本通过页面授权第 3 轮 60 次，历史调用保留。
2. 进入“创建任务”，不上传 CSV，输入下列原文，点击“理解需求”。
3. 在“任务确认”核对指标、方法、显式参数、连续点数及评价目标，再点击“生成并验证”。
4. 完成后查看“结果概览”的最终指标和候选比较；开发集选优，最终测试不参与选择。
5. 打开“运行与验证”核对版本、来源、协议和检查；在“知识依据”核对引用与发布回执。
6. 下载报告 JSON，在服务器与绑定任务、源码、验证记录和图谱独立核对。

> {r['requirement']}

{fig(label, 0)}
"""
    if label == 'memory' or label == 'disk':
        text += fig(label, 1) + '\n'
    if label == 'repair':
        text += """修复实验使用独立 18504 页面，先显示明确故障注入提示。仅验收副本将页面提交连接到已有 `fault_injection` 开关，原有生成、验证、修复算法均未改动；普通三个场景的注入开关为 false。

真实模型原稿单独保留，再对 v0 有效输出分数加 1.0，故意触发边界属性失败；原稿未单独复验，不宣称注入前已通过。v1 由真实模型根据 `previous_source` 和 `development_feedback` 生成。此案例不计自然错误修复率。

"""
    text += f"""## 2. 候选、版本及工程检查

| 候选版本 | 来源 | 工程结果 | 实际检查记录数 |
| --- | --- | --- | ---: |
{chr(10).join(version_rows)}

检查数包括不同层的同名检查，不等于独立属性种类数。最终通过版本为 `reference_verified`，表示通过列出的契约、属性和有限反例参考比较，不是数学证明。

开发集以 {('事件' if selection['objective'] == 'event_detection' else '点级')} Fβ 为主要依据，β={selection.get('beta', 1):g}；下表列点级指标，完整排序次级条件见冻结选优记录。

| 方法 / 候选 | 末版工程检查 | 开发点 Precision | 开发点 Recall | 开发点 Fβ | 排名 |
| --- | --- | ---: | ---: | ---: | ---: |
{chr(10).join(candidate_rows)}

"""
    if label == 'cpu':
        text += fig(label, 2) + '\n'
    elif label == 'memory':
        text += fig(label, 3) + '\n' + fig(label, 4) + '\n' + fig(label, 5) + '\n'
    elif label == 'disk':
        text += fig(label, 3) + '\n' + fig(label, 4) + '\n'
    else:
        text += fig(label, 2) + '\n' + fig(label, 3) + '\n' + fig(label, 4) + '\n'
        versions = r['candidates'][0]['versions']
        text += f"v1 的父版本摘要为 `{versions[1]['parent_source_sha256']}`，与实际失败 v0 的 `{versions[0]['source_sha256']}` 一致。失败与通过版本都保留，没有覆盖 v0。\n\n"
    text += '\n'.join(source_links) + '\n\n'
    text += f"""## 3. 最终测试结果

| 指标 | 采用方案的最终测试结果 |
| --- | ---: |
| 计分点 / 真实事件 | {point['total']} / {event['tp'] + event['fn']} |
| 点 Precision / Recall / F1 | {fmt(metric(point, 'precision'))} / {fmt(metric(point, 'recall'))} / {fmt(metric(point, 'f1'))} |
| 点 TP / FP / FN / TN | {point['tp']} / {point['fp']} / {point['fn']} / {point['tn']} |
| 事件 F1；TP / FP / FN | {fmt(metric(event, 'f1'))}；{event['tp']} / {event['fp']} / {event['fn']} |
| 匹配延迟中位数 | {final['matched_delay_seconds']['median']:g} 秒 |
| 正常误报频次 | {metric(final, 'normal_false_alarms_per_host_hour'):g} 次/主机小时 |
| 可判定覆盖率 | {metric(final, 'coverage'):.0%} |

**覆盖率是可判定点比例，不是异常区间召回率。** 保留 `LOW_EVENT_COUNT`，模拟事件少且未定义业务验收门槛，不据此宣称生产效果达标。

"""
    if label == 'cpu':
        text += '连续三点规则仍漏掉较短异常，本轮漏检 1 个事件；零正常误报不等于没有漏检。\n\n' + fig(label, 1) + '\n'
    elif label == 'memory':
        text += '本轮有 15 个点级误报和 5 个漏检点。正常误报频次按事件口径计数，不能用其为零推断点级 FP 为零。开发点级 F1 与最终测试值分开保留，不沿用旧轮指标。\n\n' + fig(label, 2) + '\n'
    elif label == 'disk':
        text += '事件匹配成功不表示完整覆盖异常区间。点级召回和匹配延迟仍须单独评估，不以事件 F1 掩盖漏检点。\n\n' + fig(label, 2) + '\n'
    else:
        text += fig(label, 1) + '\n'
    text += f"""## 4. 知识、经验及回写

实际提供知识 {len(knowledge['supplied'])} 条、显式引用 {len(knowledge['cited'])} 条；提供经验 {len(knowledge['supplied_experiences'])} 条、引用 {len(knowledge['cited_experiences'])} 条；没有未提供知识引用。算法冻结规格来自专家注册卡片及其引用原文，卡片来源为 `reference`，本次通过实现为 `llm_api`。

独立知识命名空间初始经验数为 0；只复用此前已来源校验的材料，没有复制历史实现或经验，也没有重新执行材料导入。

"""
    if label == 'cpu':
        text += fig(label, 3) + '\n' + fig(label, 4) + '\n'
    elif label == 'memory':
        text += '本轮固定阈值候选还显式引用了本轮 CPU 任务的经验；内存任务本身完成后再发布三种方法的经验。EWMA 被采用，MAD 与固定阈值的经验保留为需重新评价的风险提示。\n\n' + fig(label, 6) + '\n'
    elif label == 'disk':
        chain = load(proof / 'experience-chain.json')
        graph = load(proof / 'knowledge-after.json')
        by_id = {n['id']: n for n in graph['nodes']}
        text += f"本轮内存任务 `{chain['memory_task_id']}` 先完成发布，再提交本磁盘任务。核验链为：内存发布节点 → 磁盘检索 → 真实代码生成 prompt → 版本 `knowledge_ids`。\n\n"
        text += '| 来自本轮内存的经验 ID | 提供 / 引用 |\n| --- | --- |\n'
        for identity in chain['provided']:
            text += f"| `{identity}` | 已提供 / {'已引用' if identity in chain['cited'] else '未引用'} |\n"
        text += '\n' + fig(label, 5) + '\n' + fig(label, 6) + '\n' + fig(label, 7) + '\n'
        text += '经验被提供和引用证明了链路，不是其提升检测效果的因果证据。\n\n'
    else:
        text += '回写同时保留失败 v0、通过 v1、对应检查和经验；整体任务仍标记 `fault_injection`。\n\n' + fig(label, 5) + '\n'
    text += f"""## 5. 用量、下载及独立核验

生成工作流记录 {usage['requests']} 次真实请求，输入/输出 token {usage['input_tokens']:,} / {usage['output_tokens']:,}，总计 {usage['total_tokens']:,}；实际工作流约 {r['workflow_runtime_seconds']:.2f} 秒。需求理解另计，共享同一账本；用量不完整时不按零计。

四个任务均通过浏览器实际下载报告，解析后与服务器绑定报告一致。所有源码摘要、父版本、冻结规格、插件文件摘要、能力 → 实现 → 验证关系和发布节点均在服务器独立核验。

- [实际下载报告]({prefix}/downloads/{label}-report.json) · [任务审计与真实模型输入摘要]({prefix}/runs/{label}/audit.json)
- [服务器完整报告]({prefix}/runs/{label}/report.json) · [冻结配置与选优]({prefix}/runs/{label}/selection.json)
- [附件校验清单]({prefix}/manifest.sha256) · [报告目录](REPORT.md)
"""
    if label == 'cpu':
        text += f"- [实际下载交付 ZIP]({prefix}/downloads/cpu-delivery.zip) · [逐字节及归档完整性核验]({prefix}/cpu-delivery-check.json)\n"
    if label == 'repair':
        text += '\n' + fig(label, 6)
    (reports / files[label]).write_text(text)
    summary[label] = {'task_id': r['task_id'], 'status': r['status'], 'selected': selection['selected'],
                      'point_f1': metric(point, 'f1'), 'point_recall': metric(point, 'recall'),
                      'event_f1': metric(event, 'f1'), 'repairs': repairs,
                      'workflow_requests': usage['requests'], 'workflow_seconds': r['workflow_runtime_seconds']}
(proof / 'results-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(summary, ensure_ascii=False))
