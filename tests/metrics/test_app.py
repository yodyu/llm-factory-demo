import pytest
from pathlib import Path


def test_page_renders_without_issuing_model_requests(tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    from factory.metrics.model import ModelGateway

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("rendering must not issue a model request")

    monkeypatch.setattr(ModelGateway, "ask", forbidden)
    monkeypatch.setenv("FACTORY_METRICS_STATE", str(tmp_path / "ui"))
    app = AppTest.from_file(Path(__file__).resolve().parents[2] / "streamlit_app.py").run(timeout=10)
    assert not app.exception
    assert app.title[0].value == "数值监控算法能力工厂"
    assert not (tmp_path / "ui").exists()


@pytest.mark.parametrize("data_source", ["simulation", "upload", "upload_labels"])
def test_page_mock_submission_executes_isolated_workflow(tmp_path, monkeypatch, data_source):
    import os
    import json
    pytest.importorskip("streamlit")
    image = os.environ.get("FACTORY_METRICS_IMAGE", os.environ.get("METRICS_DOCKER_IMAGE"))
    if not image:
        pytest.skip("需要设置 FACTORY_METRICS_IMAGE")
    from streamlit.testing.v1 import AppTest
    state = tmp_path / "ui"
    monkeypatch.setenv("FACTORY_METRICS_STATE", str(state))
    monkeypatch.setenv("FACTORY_METRICS_IMAGE", image)
    config = os.environ.get("FACTORY_NEO4J_CONFIG", os.environ.get("METRICS_NEO4J_CONFIG"))
    if not config:
        pytest.skip("需要设置 FACTORY_NEO4J_CONFIG 以运行新任务页面测试")
    from uuid import uuid4
    from factory.metrics.neo4j_store import Neo4jKnowledgeStore
    c = json.loads(Path(config).read_text())
    c["namespace"] = "metrics-ui-test-" + uuid4().hex
    graph = Neo4jKnowledgeStore(c["uri"], tuple(Path(c["auth_file"]).read_text().strip().split("/",1)), namespace=c["namespace"])
    graph.initialize()
    config_path = tmp_path / "knowledge-config.json"
    config_path.write_text(json.dumps(c))
    monkeypatch.setenv("FACTORY_METRICS_KNOWLEDGE", str(config_path))
    monkeypatch.setenv("FACTORY_METRICS_SNAPSHOT", str(tmp_path / "no-existing-snapshot.json"))
    monkeypatch.delenv("FACTORY_METRICS_MODEL_ENV", raising=False)
    monkeypatch.delenv("FACTORY_METRICS_CAMPAIGN", raising=False)
    from factory.metrics.ui_settings import save_settings
    save_settings(state, {'model_mode': 'mock', 'retrieval': 'structured', 'round_limit': 60})
    app = AppTest.from_file(Path(__file__).resolve().parents[2] / "streamlit_app.py").run(timeout=10)
    if data_source.startswith('upload'):
        import csv
        import io
        import streamlit as st
        from types import SimpleNamespace
        from factory.metrics.upload import upload_example
        raw = upload_example('cpu_spike')
        label_raw = None
        if data_source == 'upload_labels':
            rows = list(csv.DictReader(io.StringIO(raw.decode())))
            for row in rows[220:225] + rows[320:325]:
                row['value'] = '95'
            output = io.StringIO(newline='')
            writer = csv.DictWriter(output, fieldnames=['timestamp', 'host_id', 'value'], lineterminator='\n')
            writer.writeheader()
            writer.writerows(rows)
            raw = output.getvalue().encode()
            label_raw = ('timestamp,host_id,is_anomaly\n' + ''.join(
                f"{r['timestamp']},{r['host_id']},{int(220 <= i < 225 or 320 <= i < 325)}\n" for i, r in enumerate(rows) if i >= 200)).encode()
        def uploaded(*a, **kw):
            content = label_raw if kw.get('key') == 'create_labels' else raw
            return None if content is None else SimpleNamespace(name='example.csv', getvalue=lambda: content)
        monkeypatch.setattr(st, 'file_uploader', uploaded)
        app.button(key='example-上传 CSV').click().run()
    app.button(key='understand-requirement').click().run(timeout=30)
    assert not app.exception and not submit_button(app).disabled
    submit_button(app).click().run(timeout=60)
    assert not app.exception
    import time
    from factory.metrics.background import task_records
    record = task_records(state)[0]
    assert record['active']
    task_id = record['task_id']
    assert '任务仍在后台运行' in visible_text(app)
    nav(app, '创建任务')
    nav(app, '查看结果')
    assert task_id in visible_text(app)
    # A new viewer and page navigation do not own or cancel the worker process.
    fresh = AppTest.from_file(Path(__file__).resolve().parents[2] / 'streamlit_app.py')
    fresh.session_state['page'] = '结果概览'
    fresh.run(timeout=10)
    assert not fresh.exception and task_id in visible_text(fresh)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        record = next(r for r in task_records(state) if r['task_id'] == task_id)
        if not record['active']:
            break
        time.sleep(0.2)
    assert record['status'] == 'COMPLETED', record
    app.run(timeout=20)
    assert not app.exception
    reports = list(state.glob("runs/*/report.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text())
    assert report["status"] == "COMPLETED" and report["origin"] == "mock"
    assert report["campaign_budget"] is None
    assert report["model_usage"]["kind"] == "mock" and report["model_usage"]["total_tokens"] == 0
    data = next(state.glob('inputs/*/dataset'))
    if data_source == 'simulation':
        from factory.metrics.synthetic import generate
        experiment = json.loads((data / 'trusted/experiment.json').read_text())
        assert (data / 'test.csv').read_bytes() == generate('cpu_spike', seed=experiment['seeds']['train'])['observations']['test.csv']
    else:
        assert (data / 'observations.csv').read_bytes() == raw
        assert report['data_source']['type'] == 'uploaded_csv'
        assert len(report['candidates']) == 2
        assert all(c['role'] == 'development' for c in report['candidates'])
        assert report['data_source']['development_points'] == report['data_source']['test_points'] == 80
        assert report['selection']['basis'] == ('labelled_development' if data_source == 'upload_labels' else 'engineering_only')
        if data_source == 'upload_labels':
            assert report['final']['effect_status'] == 'MEASURED'
            assert report['final']['event']['tp'] == 1
            assert report['final']['event']['precision']['value'] == 1.0
            assert report['final']['point']['recall']['value'] == 0.8
            from factory.metrics.requirements import DEFAULT_LABEL_SOURCE
            assert report['data_source']['labels']['source'] == DEFAULT_LABEL_SOURCE
            assert (data / 'trusted/user-labels.csv').read_bytes() == label_raw
            assert (reports[0].parent / 'delivery.zip').is_file()
        else:
            assert report['final']['effect_status'] == 'NOT_EVALUATED'
    assert "本会话最近提交任务" in visible_text(app)
    receipt = json.loads((reports[0].parent / 'publication.json').read_text())
    assert receipt['status'] == 'PUBLISHED'
    nodes = graph.details(receipt['node_ids'])
    assert {'Implementation', 'ValidationRun', 'Experience'} <= {n['kind'] for n in nodes}
    from factory.metrics.knowledge import retrieve
    result = retrieve(graph.snapshot(), requirement='CPU', metric_kind='gauge',
                      allowed_methods=['fixed_threshold','rolling_mad'], history_points=60, origin='mock')
    assert result['experiences']
    nav(app, '知识与依据')
    assert 'PUBLISHED' in visible_text(app)
    graph._execute(lambda tx:tx.run("MATCH (n) WHERE n.namespace=$ns DETACH DELETE n",ns=graph.namespace).consume(),write=True)
    graph.close()


def test_exhausted_budget_disables_api_and_can_switch_back_to_mock(tmp_path, monkeypatch):
    import sqlite3
    pytest.importorskip("streamlit")
    from factory.metrics.budget import CallBudget
    from factory.metrics.model import ModelGateway
    from streamlit.testing.v1 import AppTest
    campaign = tmp_path / "campaign.sqlite"
    CallBudget(campaign)
    with sqlite3.connect(campaign) as db:
        db.executemany("INSERT INTO calls VALUES (?,?,'SUCCEEDED',1)", [(str(i), "hash") for i in range(60)])
    async def forbidden(*_args, **_kwargs):
        raise AssertionError("exhausted API must not send a request")
    monkeypatch.setattr(ModelGateway, "ask", forbidden)
    monkeypatch.setenv("FACTORY_METRICS_STATE", str(tmp_path / "ui"))
    monkeypatch.setenv("FACTORY_METRICS_CAMPAIGN", str(campaign))
    monkeypatch.setenv("FACTORY_METRICS_MODEL_ENV", str(tmp_path / "not-read.env"))
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text("{}")
    monkeypatch.setenv("FACTORY_METRICS_SNAPSHOT", str(snapshot))
    app = AppTest.from_file(Path(__file__).resolve().parents[2] / "streamlit_app.py").run(timeout=10)
    nav(app, "配置")
    app.radio(key="settings_model_mode").set_value("api").run(timeout=10)
    nav(app, "创建任务")
    assert not app.exception and submit_button(app).disabled
    assert any("60/60" in caption.value for caption in app.caption)
    nav(app, "配置")
    app.radio(key="settings_model_mode").set_value("mock").run(timeout=10)
    nav(app, "创建任务")
    assert not app.button(key="understand-requirement").disabled and submit_button(app).disabled and not (tmp_path / "ui" / "runs").exists()
    with sqlite3.connect(campaign) as db:
        assert db.execute("SELECT COUNT(*) FROM calls").fetchone()[0] == 60



def submit_button(app):
    return next(b for b in app.button if b.label == "生成并验证")


def nav(app, label):
    sections = {'结果概览':'结果概览', '知识与依据':'知识与依据', '验证过程':'验证过程',
                '运行与验证':'验证过程', '知识依据':'知识与依据', '模型用量':'模型用量'}
    if label in sections:
        if app.session_state['page'] != '任务结果':
            app.button(key='nav-查看结果').click().run(timeout=20)
        return app.radio(key='result-section-widget').set_value(sections[label]).run(timeout=20)
    route = {'任务结果':'查看结果', '系统配置':'配置'}.get(label, label)
    return app.button(key="nav-" + route).click().run(timeout=20)


def visible_text(app):
    kinds = ("markdown", "caption", "warning", "error", "info", "success", "json")
    return "\n".join(str(element.value) for kind in kinds for element in app.get(kind)) + "\n" + "\n".join(e.label for e in app.expander)


@pytest.fixture
def archived_page(tmp_path, monkeypatch):
    import json
    import shutil
    from factory.metrics.knowledge import LegacySQLiteKnowledgeStore as KnowledgeStore
    from factory.metrics.publication import publish

    root = Path(__file__).resolve().parents[2]
    state = tmp_path / "ui"
    directory = state / "runs" / "archived-real"
    shutil.copytree(root / "case-example/metrics/delivery/real-memory-v1", directory)
    report = json.loads((directory / "report.json").read_text())
    knowledge = KnowledgeStore(tmp_path / "knowledge.sqlite")
    receipt = publish(knowledge, report)
    (directory / "publication.json").write_text(json.dumps(receipt))
    (state / "runtime.sqlite").write_bytes(b"viewing must not open this ledger")
    monkeypatch.setenv("FACTORY_METRICS_STATE", str(state))
    monkeypatch.setenv("FACTORY_METRICS_KNOWLEDGE", str(knowledge.path))
    monkeypatch.delenv("FACTORY_METRICS_CAMPAIGN", raising=False)
    monkeypatch.delenv("FACTORY_METRICS_MODEL_ENV", raising=False)
    monkeypatch.delenv("FACTORY_METRICS_IMAGE", raising=False)
    return directory, report, knowledge.path


def forbid_execution(monkeypatch):
    from factory.metrics.model import ModelGateway
    from execution.metrics_runner import MetricsRunner
    calls = []
    def forbidden(*_args, **_kwargs):
        calls.append("side effect")
        raise AssertionError("evidence review must not execute or publish")
    async def forbidden_async(*_args, **_kwargs):
        return forbidden()
    monkeypatch.setattr("factory.metrics.service.run_command", forbidden_async)
    monkeypatch.setattr("factory.metrics.background.submit", forbidden)
    monkeypatch.setattr(ModelGateway, "ask", forbidden_async)
    monkeypatch.setattr("factory.metrics.workflow.final_evaluate", forbidden)
    monkeypatch.setattr("factory.metrics.publication.publish", forbidden)
    monkeypatch.setattr("factory.metrics.generation.generate", forbidden_async)
    monkeypatch.setattr(MetricsRunner, "detector", forbidden)
    return calls


def test_archive_review_exposes_evidence_and_reruns_are_read_only(archived_page, tmp_path, monkeypatch):
    import hashlib
    from streamlit.testing.v1 import AppTest
    directory, report, _ = archived_page
    calls = forbid_execution(monkeypatch)
    before = {str(p.relative_to(tmp_path)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in tmp_path.rglob("*") if p.is_file()}
    app = AppTest.from_file(Path(__file__).resolve().parents[2] / "streamlit_app.py").run(timeout=10)
    assert not app.exception
    nav(app, "查看结果")
    chosen = app.session_state["selected_task"]
    texts = [visible_text(app)]
    for section in ("知识与依据", "验证过程", "结果概览"):
        nav(app, section)
        assert not app.exception and app.session_state["selected_task"] == chosen
        texts.append(visible_text(app))
    text = "\n".join(texts)
    for expected in ("历史保存任务", report["task"]["task_id"], "第 2 轮代码修复", "PUBLISHED", "适用范围", "实际提供给模型", "显式引用", "未显式引用经验"):
        assert expected in text
    labels = [element.proto.label for element in app.get("download_button")]
    assert "下载报告 JSON" in labels
    nav(app, "创建任务")
    app.text_area[0].set_value("仅查看历史任务，不提交").run(timeout=10)
    assert not app.exception and submit_button(app).disabled
    nav(app, "查看结果")
    assert app.session_state["selected_task"] == chosen
    after = {str(p.relative_to(tmp_path)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in tmp_path.rglob("*") if p.is_file()}
    assert before == after and calls == []


def test_tampered_latest_source_is_not_offered_for_download(archived_page, monkeypatch):
    from streamlit.testing.v1 import AppTest
    directory, report, _ = archived_page
    candidate = report["candidates"][0]
    source = directory / candidate["versions"][-1]["source_path"]
    source.write_text(source.read_text() + "\n# changed after validation")
    calls = forbid_execution(monkeypatch)
    app = AppTest.from_file(Path(__file__).resolve().parents[2] / "streamlit_app.py").run(timeout=10)
    nav(app, "查看结果")
    assert not app.exception and "源码摘要与验证记录不一致" in visible_text(app)
    labels = [element.proto.label for element in app.get("download_button")]
    assert "下载 " + candidate["candidate_id"] + " 源码" not in labels
    assert "下载报告 JSON" in labels and not calls


@pytest.mark.parametrize("origin", ["historical", "fault_injection", "mock"])
def test_missing_final_metrics_and_old_validator_warning_stay_explicit(archived_page, monkeypatch, origin):
    import json
    from streamlit.testing.v1 import AppTest
    directory, report, _ = archived_page
    # Controlled variants of an archived record; sealed originals are untouched.
    report["origin"] = origin
    report["final"]["event"]["precision"] = {"value": None, "null_reason": "no_predictions"}
    report["candidates"][0]["versions"][0]["validation"]["checks"].append({
        "check": "state_reload", "passed": False, "difference": {"code": "STATE_RELOAD_DIFFERENCE"}})
    (directory / "report.json").write_text(json.dumps(report))
    (directory / "publication.json").write_text(json.dumps({"status": "PENDING_RETRY", "failure": {"code": "controlled-storage-error"}}))
    calls = forbid_execution(monkeypatch)
    app = AppTest.from_file(Path(__file__).resolve().parents[2] / "streamlit_app.py").run(timeout=10)
    assert not app.exception
    nav(app, "查看结果")
    overview = visible_text(app)
    tables = [str(t.value) for t in app.table]
    nav(app, "知识与依据")
    text = overview + visible_text(app)
    assert "v1 缺陷" in text and "controlled-storage-error" in text and origin in text
    assert any("未定义（no_predictions）" in table for table in tables)
    nav(app, "模型用量")
    assert any(origin in caption.value for caption in app.caption)
    assert not calls


def test_explicit_lower_requirement_on_upper_page_stops_before_task_creation(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("FACTORY_METRICS_STATE", str(tmp_path / "ui"))
    monkeypatch.setenv("FACTORY_METRICS_IMAGE", "sha256:" + "a" * 64)
    calls = forbid_execution(monkeypatch)
    app = AppTest.from_file(Path(__file__).resolve().parents[2] / "streamlit_app.py").run(timeout=10)
    app.text_area[0].set_value("检测CPU持续下降，低于15时报警").run(timeout=10)
    assert not app.exception and submit_button(app).disabled
    assert not (tmp_path / "ui").exists() and not calls


def test_task_graph_link_and_missing_live_associations_are_readonly(archived_page, monkeypatch):
    from streamlit.testing.v1 import AppTest
    directory, report, _ = archived_page
    calls = forbid_execution(monkeypatch)
    app = AppTest.from_file(Path(__file__).resolve().parents[2] / "streamlit_app.py").run()
    nav(app, "查看结果")
    chosen = app.session_state["selected_task"]
    nav(app, "知识与依据")
    app.button(key="open-task-graph").click().run(timeout=20)
    assert not app.exception
    assert app.session_state["graph_scope"] == chosen
    assert not app.text_input and not app.slider
    assert report["task"]["task_id"] in visible_text(app)
    assert any("冻结证据" in e.label for e in app.expander)
    app.selectbox(key="graph_method").set_value("fixed_threshold").run()
    nav(app, "查看结果")
    assert app.session_state["selected_task"] == chosen and calls == []
    nav(app, "知识图谱")
    assert app.selectbox(key="graph_method").value == "fixed_threshold"
    assert app.session_state["graph_scope"] == chosen


def test_switch_between_two_tasks_then_all_result_pages(archived_page):
    import json
    import shutil
    from streamlit.testing.v1 import AppTest
    directory, report, _ = archived_page
    second = directory.parent / "second"
    shutil.copytree(directory, second)
    report["task"]["task_id"] = "second-history-task"
    (second / "report.json").write_text(json.dumps(report))
    app = AppTest.from_file(Path(__file__).resolve().parents[2] / "streamlit_app.py").run()
    nav(app, "查看结果")
    app.selectbox(key="review_task").set_value(str(directory / "report.json")).run()
    assert app.session_state["selected_task"] == str(directory / "report.json")
    for section in ("知识与依据", "验证过程", "结果概览", "创建任务", "查看结果"):
        nav(app, section)
        assert not app.exception and app.session_state["selected_task"] == str(directory / "report.json")
    app.selectbox(key="review_task").set_value(str(second / "report.json")).run()
    nav(app, "验证过程")
    assert app.session_state["selected_task"] == str(second / "report.json")


def test_invalid_submission_does_not_navigate_to_previous_run(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("FACTORY_METRICS_STATE", str(tmp_path / "ui"))
    monkeypatch.delenv("FACTORY_METRICS_IMAGE", raising=False)
    app = AppTest.from_file(Path(__file__).resolve().parents[2] / "streamlit_app.py").run()
    app.session_state["last_metrics_run"] = {"task_id": "previous", "status": "COMPLETED"}
    app.run()
    assert not app.exception and app.session_state["page"] == "创建任务"
    assert submit_button(app).disabled and "配置隔离镜像" in visible_text(app)
