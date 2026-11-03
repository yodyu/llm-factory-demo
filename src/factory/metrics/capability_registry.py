"""Explicit trusted capability plugins. Model-produced code never enters this registry."""
from functools import lru_cache
import ast
import importlib.util
import os
from pathlib import Path

from jsonschema import Draft202012Validator

from contracts.capability import CapabilityCard
from factory.metrics.spec_sources import checked_spec_sources, material_root, source_signature


def plugin_root():
    return Path(os.environ.get('FACTORY_CAPABILITIES_DIRECTORY',
                               Path(__file__).resolve().parents[3] / 'capabilities'))


class CapabilityRegistry:
    def __init__(self, root=None, *, materials=None):
        self.root = Path(root or plugin_root()).resolve()
        self.materials = Path(materials).resolve() if materials is not None else material_root()
        self.cards, self.directories = {}, {}
        for path in sorted(self.root.glob('*/capability.json')):
            if path.is_symlink() or not path.resolve().is_relative_to(self.root):
                raise ValueError('capability manifest must remain under trusted plugin root')
            card = CapabilityCard.model_validate_json(path.read_text())
            checked_spec_sources(card, self.materials)
            if card.method_id in self.cards:
                raise ValueError('duplicate capability method: ' + card.method_id)
            for name in ('checks.py', *(['reference.py'] if card.verification == 'reference' else [])):
                file = path.parent / name
                if not file.is_file() or file.is_symlink():
                    raise ValueError('missing or unsafe plugin file: ' + name)
                try:
                    tree = ast.parse(file.read_text())
                except SyntaxError:
                    raise ValueError('invalid plugin Python syntax: ' + name) from None
                functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
                required = {'cases', 'check'} if name == 'checks.py' else {'create_detector'}
                if not required <= functions:
                    raise ValueError('missing trusted plugin entrypoint: ' + name)
            self.cards[card.method_id], self.directories[card.method_id] = card, path.parent
        if not self.cards:
            raise ValueError('no capability plugins registered')

    def get(self, method):
        if method not in self.cards:
            raise ValueError('unregistered capability: ' + str(method))
        return self.cards[method]

    def validate_config(self, method, parameters):
        card = self.get(method)
        values = {**card.defaults, **parameters}
        Draft202012Validator(card.config_schema).validate(values)
        if values['direction'] not in card.supported_directions:
            raise ValueError('unsupported capability direction')
        if 'window' in values and values.get('min_history', 0) > values['window']:
            raise ValueError('min_history exceeds window')
        return values

    def module(self, method, kind):
        self.get(method)
        if kind not in ('checks', 'reference'):
            raise ValueError('invalid trusted plugin module')
        path = self.directories[method] / (kind + '.py')
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise ValueError('unsafe plugin module')
        spec = importlib.util.spec_from_file_location('trusted_capability_' + kind, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def defaults(self):
        return [method for method, card in self.cards.items() if card.default_candidate]


@lru_cache(maxsize=16)
def _cached_registry(root, signature, materials):
    return CapabilityRegistry(root, materials=materials)


def registry():
    root = plugin_root().resolve()
    signature = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size)
                      for p in sorted([*root.glob('*/capability.json'), *root.glob('*/checks.py'), *root.glob('*/reference.py')]))
    materials = material_root()
    # Reuse the parsed cards unless a plugin changes, then include material file
    # metadata in the cache key so a previously checked source cannot stay stale.
    plugins = _cached_registry(str(root), signature, str(materials))
    return _cached_registry(str(root), signature + source_signature(plugins.cards.values(), materials), str(materials))


def methods():
    return list(registry().cards)


def default_methods():
    return registry().defaults()


def validate_method(value):
    registry().get(value)
    return value


def card_for(config):
    return registry().get(config.method_id)


def needs_calibration(config):
    return card_for(config).calibration == 'quantile'


def configuration(method, explicit=None):
    from contracts.metrics import DetectorConfig
    card = registry().get(method)
    parameters = {k: v for k, v in (explicit or {}).items() if k in card.config_schema['properties']}
    for key, schema in card.config_schema['properties'].items():
        if key in parameters and schema.get('type') == 'integer' and int(parameters[key]) == parameters[key]:
            parameters[key] = int(parameters[key])
    return DetectorConfig(method_id=method, **parameters)
