"""EWMA cold start, directional smoothing and missing-value properties."""


def cases(config):
    history = config['min_history']
    return {'ewma_cold_start': [1.] * (history-1) + [10.],
            'ewma_monotonic_step': [0.] * (history+2) + [100.] * 8,
            'ewma_missing': [1.] * history + [None] * 4 + [20.]}


def check(config, name, outputs):
    if name == 'ewma_cold_start':
        return all(p['status'] == 'insufficient_history' for p in outputs[:-1]) and outputs[-1]['status'] == 'ok'
    if name == 'ewma_missing':
        return outputs[-2]['status'] == 'missing_input' and outputs[-1]['status'] == 'ok'
    values = [p['score'] for p in outputs[-8:]]
    if config['direction'] == 'lower':
        return all(a > b for a, b in zip(values, values[1:]))
    return all(a < b for a, b in zip(values, values[1:]))
