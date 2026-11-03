"""Real sandbox execution for frozen language-derived task variants."""
import asyncio
import json
import os
from pathlib import Path

import pytest

from factory.metrics.requirements import binding_for, build_draft, controlled_extract, request_from_draft


@pytest.mark.parametrize('text,methods,direction,points', [
    ('模拟CPU升高，超过90%连续三点报警，比较两种方法', ['fixed_threshold', 'rolling_mad'], 'upper', 3),
    ('模拟CPU降低，低于20%连续两点报警，只用固定阈值，每小时正常误报不超过1次，召回率不低于50%', ['fixed_threshold'], 'lower', 2),
    ('模拟CPU双向偏离，只用滚动MAD', ['rolling_mad'], 'two_sided', 2),
])
def test_language_frozen_request_executes_in_real_docker(tmp_path, text, methods, direction, points):
    image = os.environ.get('FACTORY_METRICS_IMAGE', os.environ.get('METRICS_DOCKER_IMAGE'))
    if not image:
        pytest.skip('需要设置 FACTORY_METRICS_IMAGE')
    from factory.metrics.knowledge import LegacySQLiteKnowledgeStore
    from factory.metrics.model import make_gateway
    from factory.metrics.runtime import MetricsStore
    from factory.metrics.synthetic import generate, write_dataset
    from factory.metrics.workflow import run
    from factory.metrics.reports import export_run
    draft = build_draft([text], [controlled_extract(text)], binding=binding_for([text]))
    assert not draft.issues
    request = request_from_draft(draft, current_binding=draft.binding)
    data, state = tmp_path / 'data', tmp_path / 'state'
    write_dataset(data, generate(draft.values['scenario'], direction=direction))
    store = MetricsStore(state / 'runtime.sqlite')
    gateway = make_gateway(store, mode='mock')
    knowledge = LegacySQLiteKnowledgeStore(tmp_path / 'knowledge.sqlite')
    async def launch():
        try:
            return await run(store, gateway, state=state, task_input=request.model_dump(mode='json'),
                dataset_root=data, snapshot=knowledge.snapshot(), knowledge=knowledge, image=image)
        finally:
            await gateway.client.aclose()
    result = asyncio.run(launch())
    directory = Path(result['directory'])
    report = json.loads((directory / 'report.json').read_text())
    assert report['status'] == 'COMPLETED', report.get('failure')
    assert report['task']['allowed_methods'] == methods
    assert len(report['candidates']) == len(methods)
    assert all(c['plan']['config']['direction'] == direction and c['plan']['persistence_points'] == points for c in report['candidates'])
    assert report['final_test_executed']
    if direction == 'lower':
        assert report['business_acceptance']['status'] == 'PASSED'
        assert report['candidates'][0]['business_acceptance']['status'] == 'PASSED'
    assert report['requirement_understanding']['binding'] == draft.binding
    assert (directory / 'requirement-draft.json').is_file()
    export_run(store, directory, tmp_path / 'delivery.zip', dataset_root=data)
    import zipfile
    with zipfile.ZipFile(tmp_path / 'delivery.zip') as archive:
        assert 'requirement-draft.json' in archive.namelist()
