import io
import json
from pathlib import Path
import tarfile
import zipfile

import pytest

import artifacts


def wheel(root, name='sample', version='1.2.3', python='cp314', platform='manylinux_2_28_x86_64'):
    path = root / f'{name}-{version}-{python}-{python}-{platform}.whl'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr(f'{name}-{version}.dist-info/METADATA', f'Name: {name}\nVersion: {version}\n')
        archive.writestr(f'{name}/__init__.py', '')
    return path


def conda_archive(root, name='sample', version='1.2.3', build='py314_0'):
    root.mkdir(parents=True, exist_ok=True)
    path = root / f'{name}-{version}-{build}.tar.bz2'
    record = json.dumps({'name': name, 'version': version, 'build': build,
                         'subdir': 'linux-64', 'depends': ['python >=3.14,<3.15.0a0', 'numpy >=2.3.3']}).encode()
    with tarfile.open(path, 'w:bz2') as archive:
        item = tarfile.TarInfo('info/index.json')
        item.size = len(record)
        archive.addfile(item, io.BytesIO(record))
    return path


def test_wheel_manifest_requires_all_expected_targets(tmp_path):
    path = wheel(tmp_path)
    artifacts.write_manifest(tmp_path, 'pypi', 'wheels-linux', ['cp314-manylinux_x86_64'])
    records = artifacts.verify(tmp_path, 'pypi', ['wheels-linux'], 'refs/tags/v1.2.3')
    assert records[0]['sha256'] == artifacts.sha256(path)
    with pytest.raises(ValueError, match='missing wheel'):
        artifacts.write_manifest(tmp_path, 'pypi', 'other', ['cp313-manylinux_x86_64'])


def test_corrupted_artifact_is_rejected(tmp_path):
    path = wheel(tmp_path)
    artifacts.write_manifest(tmp_path, 'pypi', 'wheels-linux')
    with path.open('ab') as stream:
        stream.write(b'corrupted')
    with pytest.raises(ValueError, match='checksum'):
        artifacts.verify(tmp_path, 'pypi')


def test_missing_platform_and_wrong_tag_are_rejected(tmp_path):
    wheel(tmp_path)
    artifacts.write_manifest(tmp_path, 'pypi', 'wheels-linux')
    with pytest.raises(ValueError, match='matrix incomplete'):
        artifacts.verify(tmp_path, 'pypi', ['wheels-linux', 'wheels-macos'])
    with pytest.raises(ValueError, match='release tag'):
        artifacts.verify(tmp_path, 'pypi', ref='refs/tags/v1.2.4')


def test_unmanifested_file_is_rejected(tmp_path):
    wheel(tmp_path)
    artifacts.write_manifest(tmp_path, 'pypi', 'wheels-linux')
    wheel(tmp_path, platform='win_amd64')
    with pytest.raises(ValueError, match='unmanifested'):
        artifacts.verify(tmp_path, 'pypi')


def test_registry_and_package_versions_must_agree(tmp_path):
    wheel(tmp_path)
    wheel(tmp_path, version='1.2.4', platform='win_amd64')
    artifacts.write_manifest(tmp_path, 'pypi', 'wheels-linux')
    with pytest.raises(ValueError, match='disagree'):
        artifacts.verify(tmp_path, 'pypi')


def test_conda_manifests_survive_merging(tmp_path):
    for label, version in [('ubuntu-latest', '3.14'), ('macos-latest', '3.14')]:
        directory = tmp_path / label
        path = conda_archive(directory, build=label)
        manifest = artifacts.write_manifest(directory, 'conda', f'conda-package-{label}-py{version}')
        path.rename(tmp_path / path.name)
        manifest.rename(tmp_path / manifest.name)
    assert len(artifacts.verify(tmp_path, 'conda', ['conda-package-ubuntu-latest-py3.14',
                                                 'conda-package-macos-latest-py3.14'])) == 2


def test_unsafe_manifest_path_is_rejected(tmp_path):
    wheel(tmp_path)
    manifest = artifacts.write_manifest(tmp_path, 'pypi', 'wheels-linux')
    record = json.loads(manifest.read_text())
    record['files'][0]['path'] = '../escape.whl'
    manifest.write_text(json.dumps(record))
    with pytest.raises(ValueError, match='unsafe'):
        artifacts.verify(tmp_path, 'pypi')


def test_conda_test_installs_exact_archive_and_declared_dependencies(tmp_path, monkeypatch):
    path = conda_archive(tmp_path)
    commands = []

    def download(command, **kwargs):
        commands.append(command)
        assert command[-3:] == ['python=3.14', 'python >=3.14,<3.15.0a0', 'numpy >=2.3.3']
        assert kwargs['clean_prefix'] == '/tmp/package-test'
        return 0

    monkeypatch.setattr(artifacts, 'retry_download', download)
    monkeypatch.setattr(artifacts.subprocess, 'run', lambda command, **kwargs: commands.append(command))
    monkeypatch.setattr(artifacts.subprocess, 'check_output', lambda *args, **kwargs: json.dumps([
        {'name': 'sample', 'version': '1.2.3', 'build_string': 'py314_0'}]))
    assert artifacts.install_conda(tmp_path, 'sample', '3.14', '/tmp/package-test', 'conda-forge') == 0
    assert commands[1][-1] == str(path.resolve())
    assert '--no-deps' in commands[1]


def test_artifact_size_limit(tmp_path):
    wheel(tmp_path)
    with pytest.raises(ValueError, match='exceeds'):
        artifacts.write_manifest(tmp_path, 'pypi', 'wheels-linux', max_size_mb=0)

def test_symlinked_artifact_is_rejected(tmp_path):
    import os
    path = wheel(tmp_path)
    manifest = artifacts.write_manifest(tmp_path, 'pypi', 'wheels-linux')
    target = tmp_path / 'original.whl'
    path.rename(target)
    try:
        path.symlink_to(target.name)
    except OSError:
        pytest.skip('symlinks unavailable on this Windows runner')
    with pytest.raises(ValueError, match='unsafe'):
        artifacts.verify(tmp_path, 'pypi')


def test_forged_wheel_tags_are_rejected(tmp_path):
    wheel(tmp_path)
    manifest = artifacts.write_manifest(tmp_path, 'pypi', 'wheels-linux')
    record = json.loads(manifest.read_text())
    record['files'][0]['python_tags'] = ['cp313']
    record['expected_wheels'] = ['cp313-manylinux_x86_64']
    manifest.write_text(json.dumps(record))
    with pytest.raises(ValueError, match='metadata'):
        artifacts.verify(tmp_path, 'pypi')


def test_conda_format_metadata_and_manifest(tmp_path):
    cph = pytest.importorskip('conda_package_handling.api')
    prefix = tmp_path / 'prefix'
    info = prefix / 'info'
    info.mkdir(parents=True)
    record = {'name': 'sample', 'version': '1.2.3', 'build': 'py314_0',
              'subdir': 'linux-64', 'depends': ['python >=3.14,<3.15.0a0']}
    (info / 'index.json').write_text(json.dumps(record))
    (info / 'files').write_text('')
    output = tmp_path / 'artifacts'
    output.mkdir()
    cph.create(str(prefix), ['info/index.json', 'info/files'], 'sample-1.2.3-py314_0.conda',
               out_folder=str(output))
    archive = output / 'sample-1.2.3-py314_0.conda'
    assert artifacts.conda_metadata(archive) == record
    artifacts.write_manifest(output, 'conda', 'conda-package-ubuntu-latest-py3.14')
    assert len(artifacts.verify(output, 'conda', ['conda-package-ubuntu-latest-py3.14'],
                                'refs/tags/v1.2.3', 'sample')) == 1
