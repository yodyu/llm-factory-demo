"""Expert authored EWMA reference; origin=reference, never a real model result."""
import json
import math


class Detector:
    def __init__(self, config):
        self.config = dict(config)
        self.baseline = None

    def fit(self, train_points):
        values = [p['value'] for p in train_points if p['value'] is not None]
        if not values:
            raise ValueError('valid training values required')
        self.baseline = sum(values) / len(values)
        self.scale = max(1e-9, math.sqrt(sum((v-self.baseline)**2 for v in values) / len(values)))
        self.reset()

    def reset(self):
        if self.baseline is None:
            raise ValueError('fit required')
        self.smooth = self.baseline
        self.count = 0

    def score_one(self, point):
        value = point['value']
        score, evidence = None, {}
        if value is None:
            status = 'missing_input'
        else:
            alpha = self.config['alpha']
            self.smooth = alpha * value + (1-alpha) * self.smooth
            self.count += int(point['original_present'])
            if self.count < self.config['min_history']:
                status = 'insufficient_history'
            else:
                status = 'ok'
                score = (self.smooth - self.baseline) / self.scale
                if self.config['direction'] == 'lower':
                    score = -score
                elif self.config['direction'] == 'two_sided':
                    score = abs(score)
                evidence = {'ewma': self.smooth, 'baseline': self.baseline, 'scale': self.scale}
        return {'timestamp': point['timestamp'], 'host_id': point['host_id'],
                'status': status, 'score': score, 'evidence': evidence}

    def save_state(self):
        return json.dumps({'config': self.config, 'baseline': self.baseline,
                           'scale': self.scale, 'smooth': self.smooth, 'count': self.count})

    def load_state(self, raw):
        value = json.loads(raw)
        if value['config'] != self.config:
            raise ValueError('state configuration mismatch')
        self.baseline, self.scale = value['baseline'], value['scale']
        self.smooth, self.count = value['smooth'], value['count']


def create_detector(config):
    return Detector(config)
