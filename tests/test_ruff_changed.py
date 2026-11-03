"""Exercise the CI lint gate with real Git histories and Ruff diagnostics."""

from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.fixture
def lint_repo(tmp_path):
    pytest.importorskip('ruff')
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    for key, value in [('user.name', 'Lint Test'), ('user.email', 'lint@example.invalid')]:
        subprocess.run(['git', '-C', str(tmp_path), 'config', key, value], check=True)
    (tmp_path / 'scripts').mkdir()
    shutil.copyfile(Path(__file__).parents[1] / 'scripts/ruff_changed.py',
                    tmp_path / 'scripts/ruff_changed.py')
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.ruff]\nextend-exclude = ["case-example"]\n')
    (tmp_path / 'app.py').write_text('print("clean")\n')
    (tmp_path / 'case-example').mkdir()
    (tmp_path / 'case-example/generated.py').write_text('print(undefined_generated_name)\n')
    subprocess.run(['git', '-C', str(tmp_path), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(tmp_path), '-c', 'core.hooksPath=/dev/null',
                    'commit', '-qm', 'root'], check=True)
    return tmp_path


def run_lint(repo, base):
    return subprocess.run([sys.executable, 'scripts/ruff_changed.py', '--base', base],
                          cwd=repo, capture_output=True, text=True)


@pytest.mark.parametrize('base', ['0' * 40, 'missing-base', 'HEAD'])
def test_missing_or_self_base_checks_root_files_and_excludes_examples(lint_repo, base):
    (lint_repo / 'app.py').write_text('print(undefined_name)\n')
    result = run_lint(lint_repo, base)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'checking all maintained Python lines' in result.stdout
    assert 'app.py:1: F821' in result.stdout
    assert 'undefined_generated_name' not in result.stdout


def test_distinct_base_checks_new_lines_without_legacy_or_example_findings(lint_repo):
    (lint_repo / 'app.py').write_text('print(legacy_undefined_name)\n')
    subprocess.run(['git', '-C', str(lint_repo), 'add', 'app.py'], check=True)
    subprocess.run(['git', '-C', str(lint_repo), '-c', 'core.hooksPath=/dev/null',
                    'commit', '-qm', 'legacy'], check=True)
    (lint_repo / 'note.txt').write_text('next commit\n')
    subprocess.run(['git', '-C', str(lint_repo), 'add', 'note.txt'], check=True)
    subprocess.run(['git', '-C', str(lint_repo), '-c', 'core.hooksPath=/dev/null',
                    'commit', '-qm', 'next'], check=True)
    (lint_repo / 'app.py').write_text('print(legacy_undefined_name)\nprint(new_undefined_name)\n')
    result = run_lint(lint_repo, 'HEAD~1')
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'app.py:2: F821' in result.stdout
    assert 'legacy_undefined_name' not in result.stdout
    assert 'undefined_generated_name' not in result.stdout


def test_clean_root_and_example_only_change_succeed(lint_repo):
    result = run_lint(lint_repo, 'HEAD')
    assert result.returncode == 0, result.stdout + result.stderr
    assert '0 new issues' in result.stdout
    (lint_repo / 'note.txt').write_text('next commit\n')
    subprocess.run(['git', '-C', str(lint_repo), 'add', 'note.txt'], check=True)
    subprocess.run(['git', '-C', str(lint_repo), '-c', 'core.hooksPath=/dev/null',
                    'commit', '-qm', 'next'], check=True)
    (lint_repo / 'case-example/generated.py').write_text('print(another_undefined_name)\n')
    result = run_lint(lint_repo, 'HEAD~1')
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'No changed Python lines.' in result.stdout
