"""Trusted property declarations; receives wire outputs, never imports generated code."""

def cases(config):
    threshold = config['threshold']
    return {'fixed_strict_boundary': [threshold - 1, threshold, threshold + 1],
            'fixed_missing': [threshold + 1, None, None, None, None, threshold]}


def check(config, name, outputs):
    if name == 'fixed_strict_boundary':
        scores = [row['score'] for row in outputs]
        return scores == ([-1, 0, 1] if config['direction'] == 'upper' else [1, 0, -1])
    return outputs[4]['status'] == 'missing_input' and outputs[4]['score'] is None
