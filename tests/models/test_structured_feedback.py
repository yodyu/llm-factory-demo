import json

import pytest
from pydantic import BaseModel, ConfigDict

from contracts.metrics_knowledge import Extraction
from factory.models.checks import validate_structured
from factory.models.transport import ModelCallError
from tests.metrics.test_knowledge import extracted


def test_nested_feedback_identifies_method_instead_of_only_capabilities(tmp_path):
    from factory.metrics.knowledge import import_material
    (tmp_path / 'a.txt').write_text('单主机 gauge')
    source, chunks = import_material(tmp_path, 'a.txt')
    value = extracted(source, chunks).model_dump(mode='json')
    value['capabilities'][0]['method_id'] = 'metrics-py312-stdlib/1'
    with pytest.raises(ModelCallError) as caught:
        validate_structured(json.dumps(value), Extraction)
    assert caught.value.validation_issues == [{
        'field': 'capabilities', 'path': 'capabilities[0].method_id',
        'type': 'string_pattern_mismatch',
    }]
    assert 'metrics-py312' not in json.dumps(caught.value.validation_issues)


def test_feedback_never_echoes_unknown_property_names_or_values():
    class Child(BaseModel):
        model_config = ConfigDict(extra='forbid', strict=True)
        count: int

    class Parent(BaseModel):
        children: list[Child]

    with pytest.raises(ModelCallError) as caught:
        validate_structured('{"children":[{"count":"password=private", "secret_key":1}]}', Parent)
    issues = caught.value.validation_issues
    assert issues[0]['path'] == 'children[0].count'
    assert issues[1]['path'] == 'children[0]'
    assert not any(word in json.dumps(issues) for word in ('password', 'private', 'secret_key'))
