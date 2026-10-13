"""Validate local interfaces and run actionlint/ShellCheck.

Actionlint 1.7.12 predates GitHub's July 2026 $/ action references. Ignore only
its exact false positive for our release-tools action; validate that reference
and its inputs here. All other actionlint diagnostics remain errors.
"""
import argparse
from pathlib import Path
import subprocess
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    document = yaml.safe_load(path.read_text())
    if True in document:  # PyYAML's YAML 1.1 treats the key `on` as a boolean.
        document['on'] = document.pop(True)
    return document


def validate_interfaces(root=ROOT):
    root = Path(root)
    for path in (root / '.github/workflows').glob('*.yml'):
        document = load(path)
        for job in document['jobs'].values():
            reference = job.get('uses', '')
            if reference.startswith('./.github/workflows/'):
                called = load(root / reference[2:])['on']['workflow_call']
                supplied = job.get('with', {})
                expected = called.get('inputs', {})
                unknown = set(supplied) - set(expected)
                required = {name for name, definition in expected.items() if definition.get('required')}
                missing = required - set(supplied)
                if unknown or missing:
                    raise ValueError(f'{path.name}: {reference}: unknown {unknown}; missing {missing}')
                secrets = job.get('secrets', {})
                if isinstance(secrets, dict) and set(secrets) - set(called.get('secrets', {})):
                    raise ValueError(f'{path.name}: unknown reusable-workflow secrets')
            for step in job.get('steps', []):
                reference = step.get('uses', '')
                if reference.startswith('$/'):
                    action = root / reference[2:] / 'action.yml'
                    if not action.is_file():
                        raise ValueError(f'unknown self-repository action: {reference}')
                    expected = load(action).get('inputs', {})
                    if set(step.get('with', {})) - set(expected):
                        raise ValueError(f'unknown action inputs: {reference}')
                if reference.startswith('MartinPdeS/MPSActions/'):
                    raise ValueError('internal actions must resolve to the running revision')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--actionlint', default='actionlint')
    parser.add_argument('--shellcheck', default='shellcheck')
    arguments = parser.parse_args()
    validate_interfaces()
    workflows = sorted(str(path) for path in (ROOT / '.github/workflows').glob('*.yml'))
    subprocess.run([arguments.actionlint, '-shellcheck', arguments.shellcheck,
                    '-ignore', r'specifying action "\$/actions/release-tools" in invalid format because ref is missing',
                    *workflows], cwd=ROOT, check=True)
    scripts = sorted(str(path) for path in ROOT.rglob('*.sh'))
    if scripts:
        subprocess.run([arguments.shellcheck, *scripts], check=True)


if __name__ == '__main__':
    main()
