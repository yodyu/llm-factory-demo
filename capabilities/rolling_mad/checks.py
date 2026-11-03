"""Past-only, missing-slot and original-history properties for this capability."""

def cases(config):
    history = [float(1 + i % 3) for i in range(config['min_history'])]
    return {'mad_past_only': history + [1000., 2.],
            'mad_zero_scale': [1.] * (config['window'] + 2) + [5.],
            'mad_missing_slots': history + [None] * (config['window'] + 4) + [2.],
            'mad_imputed_not_original': [1., None, 2., None] + history}


def check(config, name, outputs):
    if name == 'mad_past_only':
        return all(row['status'] == 'insufficient_history' for row in outputs[:config['min_history']]) and outputs[config['min_history']]['status'] == 'ok'
    if name == 'mad_missing_slots':
        return outputs[-1]['status'] == 'insufficient_history'
    if name == 'mad_imputed_not_original':
        return all(row['status'] == 'insufficient_history' for row in outputs[:min(config['min_history'], 4)])
    return outputs[-1]['status'] == 'ok' and outputs[-1]['score'] != 0
