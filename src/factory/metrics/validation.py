"""Layered validation. Only trusted plugins execute on host; candidate code stays in Docker."""
from datetime import datetime, timedelta, timezone

from contracts import FactoryError
from contracts.metrics import MetricPoint, Score
from execution.metrics_runner import CandidateFailure, check_source, DEPENDENCY_PROFILE
from factory.metrics.capability_registry import registry
from factory.metrics.data import CausalPreprocessor
from factory.metrics.legacy_validation import _same as _same
from factory.runtime.artifacts import digest

PROTOCOL = 'metrics-method-check/3'


def _points(values):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [MetricPoint(timestamp=start + timedelta(minutes=i), host_id='validation-host', value=v)
            for i, v in enumerate(values)]


def validate_candidate(runner, task_id, source, config, *, candidate_id, version, origin,
                       protocol=PROTOCOL, expected_plugin_hashes=None):
    if protocol == 'metrics-method-check/2':
        from factory.metrics.legacy_validation import validate_candidate as legacy
        return legacy(runner, task_id, source, config, candidate_id=candidate_id,
                      version=version, origin=origin)
    if protocol != PROTOCOL:
        raise ValueError('unsupported method validation protocol')
    plugins = registry()
    card = plugins.get(config.method_id)
    parameters = config.model_dump(mode='json')
    plugin_hashes = {p.name: digest(p.read_bytes()) for p in
                     plugins.directories[config.method_id].iterdir() if p.suffix in ('.json', '.py')}
    if expected_plugin_hashes and expected_plugin_hashes != plugin_hashes:
        raise ValueError('NEEDS_KNOWLEDGE: plugin changed after snapshot freeze')
    checks = plugins.module(config.method_id, 'checks')
    cases = checks.cases(parameters)
    if not isinstance(cases, dict) or not cases or len(cases) > 16 or sum(map(len, cases.values())) > 8192:
        raise ValueError('plugin must declare bounded nonempty property cases')
    report = {'protocol': PROTOCOL, 'candidate_id': candidate_id, 'version': version,
              'origin': origin, 'source_sha256': digest(source.encode()), 'config': parameters,
              'dependency_profile': DEPENDENCY_PROFILE, 'checks': [], 'passed': False,
              'repairable': True, 'verification_level': 'contract_only',
              'capability_version': card.version,
              'plugin_hashes': plugin_hashes}
    check, current_points, index = 'static_profile', [], None
    train = _points([0., 1., 2., 3.])

    def difference(expected, actual, message):
        raise CandidateFailure({'code': 'METHOD_DIFFERENCE', 'expected': expected,
                                'actual': actual, 'message': message})

    try:
        check_source(source)
        report['checks'].append({'check': check, 'passed': True, 'layer': 'contract'})
        with runner.detector(task_id, source) as detector:
            def run(values):
                nonlocal current_points, index
                current_points = _points(values)
                detector.fit(config, train)
                detector.reset()
                prep = CausalPreprocessor()
                outputs = []
                for index, point in enumerate(current_points):
                    outputs.append(detector.score_one(prep.step(point)))
                return outputs

            check = 'missing_input_contract'
            outputs = run([1., None, None, None, None, 2.])
            if outputs[4].status != 'missing_input' or outputs[4].score is not None:
                difference({'status': 'missing_input', 'score': None}, outputs[4].model_dump(mode='json'), 'missing input handling')
            report['checks'].append({'check': check, 'passed': True, 'layer': 'contract'})
            check = 'state_reload'
            state = detector.call('save')
            point = CausalPreprocessor().step(_points([0.] * 6 + [7.])[-1])
            expected = detector.score_one(point)
            detector.call('load', state=state)
            actual = detector.score_one(point)
            if not _same(expected, actual):
                difference(expected.model_dump(mode='json'), actual.model_dump(mode='json'), 'save/load changed score')
            report['checks'].append({'check': check, 'passed': True, 'layer': 'contract'})
            check = 'reset_repeat_future_invariance'
            prefix = list(cases.values())[0]
            outputs = [run(prefix + [future]) for future in (100., -100.)]
            if any(not _same(a, b) for a, b in zip(outputs[0][:-1], outputs[1][:-1])):
                difference('same past outputs', 'different past outputs', 'reset or future invariance failed')
            report['checks'].append({'check': check, 'passed': True, 'layer': 'contract'})
            for check, values in cases.items():
                actual = run(values)
                raw = [row.model_dump(mode='json') for row in actual]
                if checks.check(parameters, check, raw) is not True:
                    difference({'property': check, 'passed': True}, raw, 'capability property failed')
                report['checks'].append({'check': check, 'passed': True, 'layer': 'property', 'points': len(values)})
            report['verification_level'] = 'property_verified'
            if card.verification == 'reference':
                reference = plugins.module(config.method_id, 'reference').create_detector(parameters)
                for name, values in cases.items():
                    check = name
                    actual = run(values)
                    reference.fit([p.model_dump(mode='json') for p in train])
                    reference.reset()
                    prep = CausalPreprocessor()
                    for index, (point, output) in enumerate(zip(current_points, actual)):
                        expected = Score.model_validate(reference.score_one(prep.step(point).model_dump(mode='json')))
                        if not _same(expected, output):
                            difference(expected.model_dump(mode='json'), output.model_dump(mode='json'), 'reference differs')
                    report['checks'].append({'check': check, 'passed': True, 'layer': 'reference', 'points': len(values)})
                report['verification_level'] = 'reference_verified'
        report['passed'] = True
    except CandidateFailure as error:
        report['checks'].append({'check': check, 'passed': False, 'point_index': index,
            'development_input': [p.model_dump(mode='json') for p in current_points[:index + 1 if index is not None else 0]],
            'difference': error.feedback, 'allowed_changes': 'candidate source only; keep frozen config and interface'})
    except FactoryError as error:
        report['repairable'] = False
        report['checks'].append({'check': check, 'passed': False,
                                'difference': {'code': error.code.value, 'message': str(error)}})
    return report
