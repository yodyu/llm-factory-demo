import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from jsonschema import ValidationError as SchemaError

from contracts.capability import CapabilityCard

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('method', ['fixed_threshold', 'rolling_mad', 'ewma'])
def test_capability_card_schemas_defaults_and_verification_files(method):
    directory = ROOT / 'capabilities' / method
    card = CapabilityCard.model_validate_json((directory / 'capability.json').read_text())
    assert card.algorithm_spec and card.inputs and card.outputs
    assert (directory / 'reference.py').is_file() and (directory / 'checks.py').is_file()
    for field in ('method_id','version','display_name','task_type','inputs','outputs','config_schema','defaults',
                  'supported_directions','metric_kinds','min_history','algorithm_spec','spec_sources','evaluation_metrics','dependency_profile','verification'):
        missing = card.model_dump()
        missing.pop(field)
        with pytest.raises(ValidationError):
            CapabilityCard.model_validate(missing)
    bad = copy.deepcopy(card.model_dump())
    bad['defaults']['direction'] = 'unsupported'
    with pytest.raises((ValidationError, SchemaError)):
        CapabilityCard.model_validate(bad)
    bad = copy.deepcopy(card.model_dump())
    bad['inputs'] = {'$ref': 'https://invalid.example/schema'}
    with pytest.raises(ValueError, match='external schema'):
        CapabilityCard.model_validate(bad)


def test_registry_dynamic_config_roundtrip_and_rejects_invalid_plugins(tmp_path):
    import shutil
    from contracts.metrics import DetectorConfig, CandidatePlan, MADConfig
    from factory.metrics.capability_registry import CapabilityRegistry
    config = MADConfig(window=3, min_history=2, direction='lower')
    plan = CandidatePlan(candidate_id='roundtrip', config=config, parameter_sources={}, knowledge_ids=[], limitations=[])
    restored = CandidatePlan.model_validate_json(plan.model_dump_json())
    assert restored.config.model_dump() == config.model_dump()
    with pytest.raises(ValueError):
        DetectorConfig(method_id='not_registered')
    with pytest.raises(ValueError):
        DetectorConfig(method_id='rolling_mad', window=2, min_history=3)
    shutil.copytree(ROOT / 'capabilities/fixed_threshold', tmp_path / 'one')
    shutil.copytree(ROOT / 'capabilities/fixed_threshold', tmp_path / 'two')
    with pytest.raises(ValueError, match='duplicate'):
        CapabilityRegistry(tmp_path)
    import shutil
    shutil.rmtree(tmp_path / 'two')
    (tmp_path / 'one/checks.py').write_text('def malformed(')
    with pytest.raises(ValueError, match='Python syntax'):
        CapabilityRegistry(tmp_path)
    (tmp_path / 'one/checks.py').write_text('def cases(config):\n    return {}\n')
    with pytest.raises(ValueError, match='entrypoint'):
        CapabilityRegistry(tmp_path)
    shutil.copyfile(ROOT / 'capabilities/fixed_threshold/checks.py', tmp_path / 'one/checks.py')
    shutil.copytree(ROOT / 'capabilities/fixed_threshold', tmp_path / 'two')
    (tmp_path / 'two/capability.json').write_text('{}')
    with pytest.raises(ValidationError):
        CapabilityRegistry(tmp_path)


def property_plugin(tmp_path, monkeypatch):
    card = json.loads((ROOT / 'capabilities/fixed_threshold/capability.json').read_text())
    card.update(method_id='property_example', verification='property_only', default_candidate=False)
    directory = tmp_path / 'property_example'
    directory.mkdir(parents=True)
    (directory / 'capability.json').write_text(json.dumps(card))
    (directory / 'checks.py').write_text("def cases(config):\n    return {'monotonic_boundary': [84.,85.,86.]}\ndef check(config,name,outputs):\n    return [p['score'] for p in outputs] == [-1.,0.,1.]\n")
    monkeypatch.setenv('FACTORY_CAPABILITIES_DIRECTORY', str(tmp_path))
    return directory


def test_controlled_property_only_validation_without_reference(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from contracts.metrics import DetectorConfig, Score
    from factory.metrics.validation import validate_candidate
    directory = property_plugin(tmp_path, monkeypatch)
    class Detector:
        wrong = False
        def fit(self, config, points):
            self.threshold = config.threshold
        def reset(self):
            pass
        def call(self, op, **kwargs):
            return '{}'
        def score_one(self, point):
            return Score(timestamp=point.timestamp, host_id=point.host_id,
                status='missing_input' if point.value is None else 'ok',
                score=None if point.value is None else point.value + self.threshold if self.wrong else point.value - self.threshold)
    class ControlledRunner:
        wrong = False
        @contextmanager
        def detector(self, *args):
            detector = Detector()
            detector.wrong = self.wrong
            yield detector
    runner = ControlledRunner()
    config = DetectorConfig(method_id='property_example')
    arguments = dict(candidate_id='property', version=0, origin='mock')
    source = 'def create_detector(config):\n    return None\n'
    report = validate_candidate(runner, 'controlled', source, config, **arguments)
    assert not (directory / 'reference.py').exists()
    assert report['passed'] and report['verification_level'] == 'property_verified'
    runner.wrong = True
    failed = validate_candidate(runner, 'controlled', source, config, **arguments)
    assert not failed['passed'] and failed['checks'][-1]['check'] == 'monotonic_boundary'


def test_v2_plugin_graph_fields_provenance_versions_and_v1_compatibility(tmp_path, monkeypatch):
    import shutil
    from factory.metrics.capability_knowledge import register_plugins
    from factory.metrics.local_store import LocalKnowledgeStore
    from factory.metrics.knowledge import verify_snapshot, retrieve
    from factory.metrics.capability_registry import registry
    from factory.metrics.capability_knowledge import plugin_records
    plugins = registry()
    card = plugins.get('fixed_threshold')
    with pytest.raises(ValueError, match='manifest field evidence mismatch'):
        plugin_records(card.model_copy(update={'algorithm_spec': 'unsupported altered claim'}), plugins.directories[card.method_id])
    store = LocalKnowledgeStore(tmp_path / 'knowledge.sqlite')
    register_plugins(store)
    snapshot = store.snapshot()
    assert snapshot['schema_version'] == 'metrics-knowledge/2'
    assert verify_snapshot(snapshot) == snapshot
    assert {'DataContract', 'Metric', 'Environment'} <= {n['kind'] for n in snapshot['nodes']}
    assert {'CONSUMES','PRODUCES','EVALUATED_WITH','DEPENDS_ON'} <= {r['relation'] for r in snapshot['relations']}
    found = retrieve(snapshot, requirement='内存', metric_kind='gauge', allowed_methods=['fixed_threshold','rolling_mad'],history_points=60,origin='mock')
    assert len(found['capabilities']) == 2
    assert all(c['field_evidence']['algorithm_spec'] for c in found['capabilities'])
    assert all(c['origin'] == 'reference' for c in found['capabilities'])
    by_id = {n['id']: n for n in snapshot['nodes']}
    for edge in snapshot['relations']:
        if edge['relation'] == 'REQUIRES':
            constraint = by_id[edge['target']]['payload']
            cite = constraint['citations'][0]
            fragment = by_id[cite['chunk_id']]['payload']['text']
            assert cite['quote'] in fragment
            assert constraint['description'] in json.loads('{' + fragment + '}')['assumptions']


    plugins = tmp_path / 'plugins'
    shutil.copytree(ROOT / 'capabilities', plugins)
    path = plugins / 'fixed_threshold/capability.json'
    changed = json.loads(path.read_text())
    changed['version'] = '2.0.0'
    changed['algorithm_spec'] += ' Versioned clarification.'
    path.write_text(json.dumps(changed, ensure_ascii=False))
    monkeypatch.setenv('FACTORY_CAPABILITIES_DIRECTORY', str(plugins))
    register_plugins(store)
    assert any(r['relation'] == 'SUPERSEDES' for r in store.snapshot()['relations'])
    changed['algorithm_spec'] += ' Illegal same-version change.'
    path.write_text(json.dumps(changed, ensure_ascii=False))
    with pytest.raises(ValueError, match='version is immutable'):
        register_plugins(store)


def test_property_only_in_real_sandbox(tmp_path, monkeypatch):
    import os
    from execution.metrics_runner import MetricsRunner
    from factory.metrics.runtime import MetricsStore
    from factory.metrics.validation import validate_candidate
    from contracts.metrics import DetectorConfig
    from tests.metrics.test_runtime import task
    image = os.environ.get('FACTORY_METRICS_IMAGE')
    if not image:
        pytest.skip('需要设置 FACTORY_METRICS_IMAGE 以验证无参考插件的真实沙箱')
    property_plugin(tmp_path / 'plugins', monkeypatch)
    store = MetricsStore(tmp_path / 'runtime.sqlite')
    spec = task(allowed_methods=['property_example'])
    store.create_task(spec)
    runner = MetricsRunner(store, store.artifact_store, tmp_path / 'packages', tmp_path / 'work', image=image)
    source = (ROOT / 'capabilities/fixed_threshold/reference.py').read_text()
    report = validate_candidate(runner, spec.task_id, source, DetectorConfig(method_id='property_example'),
                                candidate_id='property', version=0, origin='reference')
    assert report['passed'] and report['verification_level'] == 'property_verified'


def test_graph_view_covers_every_registered_knowledge_entity_kind():
    import re
    from factory.metrics.knowledge import KINDS
    template = (ROOT / 'src/factory/metrics/graph_canvas.html').read_text()
    for name in ('colors', 'names', 'fields'):
        body = re.search('const ' + name + r'=\{(.*?)\};', template).group(1)
        rendered = set(re.findall(r'(?:^|,)([A-Za-z]+):', body))
        assert KINDS <= rendered, (name, KINDS - rendered)
