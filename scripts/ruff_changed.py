"""Run Ruff on changed Python lines without hiding new errors in legacy files."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


def changed_lines(diff):
    selected = {}
    path = None
    for line in diff.splitlines():
        if line.startswith('+++ b/'):
            path = line[6:]
        elif path and line.startswith('@@'):
            match = re.search(r'\+(\d+)(?:,(\d+))? @@', line)
            if match:
                start = int(match[1])
                size = int(match[2]) if match[2] is not None else 1
                selected.setdefault(path, set()).update(range(start, start + size))
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    args = parser.parse_args()
    resolved = subprocess.run(['git', 'rev-parse', '--verify', '--quiet',
                               f'{args.base}^{{commit}}'], capture_output=True, text=True)
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], check=True,
                          capture_output=True, text=True).stdout.strip()
    if resolved.returncode or resolved.stdout.strip() == head:
        base = subprocess.run(['git', 'hash-object', '-t', 'tree', '-w', '--stdin'],
                              input='', check=True, capture_output=True, text=True).stdout.strip()
        print('No distinct comparison commit; checking all maintained Python lines.')
    else:
        base = resolved.stdout.strip()
    diff = subprocess.run(['git', 'diff', '--no-ext-diff', '--unified=0', base,
                           '--', '*.py', ':(exclude)case-example/**'],
                          check=True, capture_output=True, text=True).stdout
    lines = changed_lines(diff)
    paths = [p for p in lines if Path(p).is_file()]
    if not paths:
        print('No changed Python lines.')
        return 0
    print(f'Checking {len(paths)} maintained Python files, '
          f'{sum(len(lines[path]) for path in paths)} changed lines.')
    result = subprocess.run([sys.executable, '-m', 'ruff', 'check', '--output-format=json',
                             '--force-exclude', *paths], capture_output=True, text=True)
    if result.returncode not in (0, 1):
        print(result.stderr)
        return result.returncode
    findings = []
    for issue in json.loads(result.stdout):
        path = str(Path(issue['filename']).relative_to(Path.cwd()))
        if issue['location']['row'] in lines.get(path, set()):
            findings.append(issue)
            print(f"{path}:{issue['location']['row']}: {issue['code']} {issue['message']}")
    print(f'Ruff changed lines: {len(findings)} new issues.')
    return int(bool(findings))


if __name__ == '__main__':
    raise SystemExit(main())
