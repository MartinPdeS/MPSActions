import io
from pathlib import Path
import subprocess
import sys

import pytest

from retry import run


class Process:
    def __init__(self, status, output):
        self.stdout = io.StringIO(output)
        self.status = status

    def wait(self):
        return self.status


@pytest.mark.parametrize('failures,expected,status', [(0, 1, 0), (3, 4, 0), (4, 4, 17)])
def test_three_additional_retries(failures, expected, status):
    calls, waits = [], []

    def runner(command, **kwargs):
        calls.append(command)
        return Process(17, '502 Server Error: Bad Gateway\n') if len(calls) <= failures else Process(0, '')

    assert run(['conda', 'create', 'argument with spaces'], runner=runner, sleep=waits.append) == status
    assert len(calls) == expected
    assert all(call[-1] == 'argument with spaces' for call in calls)
    assert waits == [10, 20, 30][:expected - 1]


@pytest.mark.parametrize('output', ['LibMambaUnsatisfiableError: conflict', 'PackagesNotFoundError',
                                   'HTTPError: 401 Client Error: Unauthorized', 'CondaHTTPError: HTTP 404 Not Found',
                                   'AssertionError: test failed',
                                   '502 Bad Gateway\nResolutionImpossible'])
def test_permanent_errors_are_not_retried(output):
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        return Process(7, output)

    assert run(['operation'], runner=runner, sleep=lambda delay: pytest.fail('unexpected sleep')) == 7
    assert len(calls) == 1


def test_retry_recreates_only_a_temporary_environment(tmp_path, monkeypatch):
    monkeypatch.setenv('RUNNER_TEMP', str(tmp_path))
    prefix = tmp_path / 'environment'
    calls = []

    def runner(command, **kwargs):
        assert not prefix.exists()
        prefix.mkdir()
        (prefix / 'partial').touch()
        calls.append(command)
        return Process(1, 'ReadTimeout') if len(calls) == 1 else Process(0, '')

    assert run(['conda'], clean_prefix=prefix, runner=runner, sleep=lambda delay: None) == 0
    assert len(calls) == 2
    with pytest.raises(ValueError, match='inside RUNNER_TEMP'):
        run(['conda'], clean_prefix=tmp_path.parent)


def test_real_process_preserves_exit_status_and_output(capsys):
    status = run([sys.executable, '-c', "print('ordinary failure'); raise SystemExit(23)"], delay=0)
    assert status == 23
    assert 'ordinary failure' in capsys.readouterr().out


@pytest.mark.parametrize('retries,delay', [(-1, 0), (11, 0), (0, -1), (0, 61)])
def test_invalid_retry_configuration(retries, delay):
    with pytest.raises(ValueError):
        run(['never executed'], retries=retries, delay=delay)


def test_retry_command_line_with_real_failing_process(tmp_path):
    script = tmp_path / 'download.py'
    counter = tmp_path / 'attempts'
    script.write_text(
        "from pathlib import Path\n"
        f"counter = Path({str(counter)!r})\n"
        "count = int(counter.read_text()) + 1 if counter.exists() else 1\n"
        "counter.write_text(str(count))\n"
        "if count <= 3:\n"
        "    print('HTTPError: 502 Server Error: Bad Gateway')\n"
        "    raise SystemExit(17)\n"
    )
    helper = Path(__file__).resolve().parents[1] / 'actions/release-tools/retry.py'
    result = subprocess.run([sys.executable, str(helper), '--retries', '3', '--delay', '0',
                             '--', sys.executable, str(script)], capture_output=True, text=True)
    assert result.returncode == 0
    assert counter.read_text() == '4'
    assert result.stdout.count('::warning::') == 3
