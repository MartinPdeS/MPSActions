import subprocess

import pytest

import artifacts
import publish
from test_artifacts import wheel


def test_identical_published_file_is_skipped(tmp_path, monkeypatch):
    path = wheel(tmp_path)
    artifacts.write_manifest(tmp_path, 'pypi', 'wheels-linux')
    monkeypatch.setenv('TWINE_PASSWORD', 'test-token')
    calls = []
    publish.publish(tmp_path, 'pypi', ['wheels-linux'],
                    remote=lambda *args: artifacts.sha256(path),
                    runner=lambda command, **kwargs: calls.append(command))
    assert len(calls) == 1  # Metadata check only; no upload.
    assert calls[0][2:4] == ['twine', 'check']


def test_different_published_file_is_never_overwritten(tmp_path, monkeypatch):
    wheel(tmp_path)
    artifacts.write_manifest(tmp_path, 'pypi', 'wheels-linux')
    monkeypatch.setenv('TWINE_PASSWORD', 'test-token')
    calls = []
    with pytest.raises(ValueError, match='refusing to replace'):
        publish.publish(tmp_path, 'pypi', ['wheels-linux'], remote=lambda *args: 'different',
                        runner=lambda command, **kwargs: calls.append(command))
    assert len(calls) == 1


def test_new_file_uses_existing_token_environment(tmp_path, monkeypatch):
    wheel(tmp_path)
    artifacts.write_manifest(tmp_path, 'pypi', 'wheels-linux')
    monkeypatch.setenv('TWINE_PASSWORD', 'test-token')
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        assert 'test-token' not in command
        return subprocess.CompletedProcess(command, 0)

    publish.publish(tmp_path, 'pypi', ['wheels-linux'], remote=lambda *args: None, runner=runner)
    assert calls[1][2:4] == ['twine', 'upload']


def test_corrupted_artifact_cannot_reach_upload(tmp_path, monkeypatch):
    path = wheel(tmp_path)
    artifacts.write_manifest(tmp_path, 'pypi', 'wheels-linux')
    path.write_bytes(b'corrupted')
    monkeypatch.setenv('TWINE_PASSWORD', 'test-token')
    with pytest.raises(ValueError, match='checksum'):
        publish.publish(tmp_path, 'pypi', ['wheels-linux'], runner=lambda *args, **kwargs: pytest.fail('upload'))

def test_metadata_fetch_retries_502_but_not_authentication(monkeypatch):
    import io
    from urllib.error import HTTPError
    calls, waits = [], []
    monkeypatch.setenv('MPS_RETRIES', '3')
    monkeypatch.setenv('MPS_RETRY_DELAY', '10')

    def opener(url, **kwargs):
        calls.append(url)
        if len(calls) <= 3:
            raise HTTPError(url, 502, 'Bad Gateway', {}, None)
        return io.BytesIO(b'{"urls": []}')

    assert publish.fetch('https://example.test', opener=opener, sleep=waits.append) == {'urls': []}
    assert len(calls) == 4
    assert waits == [10, 20, 30]
    with pytest.raises(HTTPError):
        publish.fetch('https://example.test', opener=lambda url, **kwargs: (_ for _ in ()).throw(
            HTTPError(url, 403, 'Forbidden', {}, None)), sleep=lambda delay: pytest.fail('unexpected retry'))


def test_missing_remote_package_is_not_an_upload_failure():
    from urllib.error import HTTPError

    def opener(url, **kwargs):
        raise HTTPError(url, 404, 'Not Found', {}, None)

    assert publish.fetch('https://example.test', opener=opener) is None
