"""Small persistent UI preferences. No model configuration secrets are editable."""
import json
import os
from pathlib import Path
import tempfile

DEFAULTS = {'model_mode': 'api', 'round_limit': 60}
ROUND_LIMITS = (60, 150, 300, 600)


def initialize_campaign(path):
    """Create the initial ledger at the configured path, preserving existing files."""
    if not path:
        return
    path = Path(path)
    if path.is_symlink():
        raise ValueError('额度账本不能为符号链接')
    if not path.exists():
        from factory.metrics.budget import CallBudget
        CallBudget(path)


def load_settings(state):
    path = Path(state) / 'ui-settings.json'
    if not path.is_file():
        return dict(DEFAULTS)
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or data.get('model_mode') not in ('mock', 'api') or type(data.get('round_limit')) is not int or data['round_limit'] not in ROUND_LIMITS:
        raise ValueError('页面配置无效，请检查 ui-settings.json')
    # The retired retrieval preference is ignored; Web submissions always use
    # frozen capability retrieval. Reading legacy preferences stays read-only.
    return {key: data[key] for key in DEFAULTS}


def save_settings(state, settings):
    # Validate before touching the filesystem.
    if settings.get('model_mode') not in ('mock', 'api') or type(settings.get('round_limit')) is not int or settings['round_limit'] not in ROUND_LIMITS:
        raise ValueError('无效页面配置')
    state = Path(state)
    state.mkdir(parents=True, exist_ok=True)
    destination = state / 'ui-settings.json'
    if destination.is_symlink():
        raise ValueError('配置文件不能为符号链接')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=state, prefix='.ui-settings-', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({key: settings[key] for key in DEFAULTS}, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def configured_model_id(env_file):
    """Only return the allowlisted model identifier, never endpoints or keys."""
    if not env_file:
        return None
    try:
        with Path(env_file).open() as stream:
            for line in stream:
                key, separator, value = line.strip().partition('=')
                if separator and key.strip().removeprefix('export ').strip() == 'LLM_MODEL':
                    return value.strip().strip(chr(34) + chr(39)) or None
    except OSError:
        return None
    return None
