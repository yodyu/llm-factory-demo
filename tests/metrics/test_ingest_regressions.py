import asyncio

import pytest

from contracts import ErrorCode
from factory.metrics.knowledge import EvidenceError, checked_extraction, import_material, ingest
from factory.metrics.local_store import LocalKnowledgeStore
from factory.models.transport import ModelCallError
from tests.metrics.test_knowledge import extracted


class Documents:
    def __init__(self):
        self.records = []

    def register_document(self, task_id, record, kind):
        self.records.append((kind, record))


class Gateway:
    prompt_version = 'regression'

    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.store = Documents()
        self.calls = []

    async def ask(self, *args):
        self.calls.append(args)
        result = next(self.outputs)
        if isinstance(result, Exception):
            raise result
        return result


def test_partial_spec_feedback_names_missing_fields_and_correction_explains_fallback(tmp_path):
    (tmp_path / 'a.txt').write_text('只有算法公式，没有完整版本和输入输出定义。')
    source, chunks = import_material(tmp_path, 'a.txt')
    partial = extracted(source, chunks, algorithm_spec='只有算法公式')
    with pytest.raises(EvidenceError) as caught:
        checked_extraction(source, chunks, partial, origin='llm_api', response_evidence={})
    assert 'version' in caught.value.feedback['missing_values']
    assert 'algorithm_spec' in caught.value.feedback['missing_evidence']
    gateway = Gateway([partial, extracted(source, chunks)])
    store = LocalKnowledgeStore(tmp_path / 'knowledge.sqlite')
    result = asyncio.run(ingest(tmp_path, ['a.txt'], store, gateway, 'ingest-test', origin='llm_api'))
    assert result['sources'][0]['status'] == 'source_checked'
    assert 'algorithm_spec' in gateway.calls[1][4] and 'null' in gateway.calls[1][4]
    assert 'version' in gateway.calls[1][3]['feedback']['missing_values']
    assert all(n['payload'].get('implementation_verified') is False
               for n in result['snapshot']['nodes'] if n['kind'] == 'Capability')


@pytest.mark.parametrize('during_correction', [False, True])
def test_invalid_structured_source_is_recorded_and_next_material_still_runs(tmp_path, during_correction):
    for path in ('a.txt', 'b.txt'):
        (tmp_path / path).write_text('单主机 gauge：' + path)
    source, chunks = import_material(tmp_path, 'a.txt')
    next_source, next_chunks = import_material(tmp_path, 'b.txt')
    error = ModelCallError(ErrorCode.MODEL_OUTPUT_INVALID, 'structured_output_invalid',
                          validation_issues=[{'field': 'capabilities', 'type': 'string_pattern_mismatch'}])
    outputs = ([extracted(source, chunks, algorithm_spec='partial')] if during_correction else [])
    gateway = Gateway([*outputs, error, extracted(next_source, next_chunks)])
    store = LocalKnowledgeStore(tmp_path / 'knowledge.sqlite')
    result = asyncio.run(ingest(tmp_path, ['a.txt', 'b.txt'], store, gateway, 'ingest-test', origin='llm_api'))
    rejected, accepted = result['sources']
    assert rejected['status'] == 'REJECTED' and rejected['feedback']['code'] == 'MODEL_OUTPUT_INVALID'
    assert accepted['status'] == 'source_checked'
    assert [n['payload']['path'] for n in result['snapshot']['nodes'] if n['kind'] == 'Source'] == ['b.txt']
    assert len([r for kind, r in gateway.store.records if kind == 'extraction-check']) == 2


@pytest.mark.parametrize('code,reason', [
    (ErrorCode.MODEL_TIMEOUT, 'timeout'),
    (ErrorCode.MODEL_OUTPUT_INVALID, 'credential_content_rejected'),
])
def test_transport_or_credential_failure_is_not_reclassified_as_bad_material(tmp_path, code, reason):
    (tmp_path / 'a.txt').write_text('单主机 gauge')
    error = ModelCallError(code, reason, outcome_unknown=True)
    gateway = Gateway([error])
    with pytest.raises(ModelCallError) as caught:
        asyncio.run(ingest(tmp_path, ['a.txt'], LocalKnowledgeStore(tmp_path / 'knowledge.sqlite'),
                           gateway, 'ingest-test', origin='llm_api'))
    assert caught.value is error
