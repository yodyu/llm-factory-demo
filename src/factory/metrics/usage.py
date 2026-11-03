"""Task usage from frozen transport-operation metadata, never inferred billing."""
import json


def model_usage(report):
    task = report.get('task') or {}
    if task.get('model_mode') == 'mock' or report.get('origin') == 'mock':
        return {'kind': 'mock', 'requests': 0, 'input_tokens': 0, 'output_tokens': 0,
                'total_tokens': 0, 'missing_usage_requests': 0, 'reservations': 0}
    if report.get('model_calls') == 0 and not report.get('model_operations'):
        return {'kind': 'replay', 'requests': 0, 'input_tokens': 0, 'output_tokens': 0,
                'total_tokens': 0, 'missing_usage_requests': 0, 'reservations': 0}
    if 'model_operations' not in report:
        return {'kind': 'not_recorded', 'requests': None, 'input_tokens': None,
                'output_tokens': None, 'total_tokens': None, 'missing_usage_requests': None,
                'reservations': None}
    attempts = []
    for operation in report['model_operations']:
        metadata = operation.get('metadata') or {}
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (ValueError, TypeError):
                metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        if operation.get('result_ref') or operation.get('status') in {'SENT', 'UNKNOWN', 'SUCCEEDED'} or 'elapsed_seconds' in metadata:
            attempts.append(metadata)
    def valid(value):
        return type(value) is int and value >= 0
    input_known = sum(m['input_tokens'] for m in attempts if valid(m.get('input_tokens')))
    output_known = sum(m['output_tokens'] for m in attempts if valid(m.get('output_tokens')))
    missing = sum(not (valid(m.get('input_tokens')) and valid(m.get('output_tokens'))) for m in attempts)
    return {'kind': 'api', 'requests': len(attempts), 'reservations': len(report['model_operations']),
            'input_tokens': input_known if not attempts or any(valid(m.get('input_tokens')) for m in attempts) else None,
            'output_tokens': output_known if not attempts or any(valid(m.get('output_tokens')) for m in attempts) else None,
            'total_tokens': None if missing else input_known + output_known,
            'missing_usage_requests': missing,
            'notice': 'Counts include retries and repairs; tokens are provider-reported only; missing usage is not zero.'}
