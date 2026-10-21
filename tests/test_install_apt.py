from pathlib import Path

import pytest

from install_apt import install


@pytest.mark.parametrize('relative', ['sources.list.d/ubuntu.sources', 'sources.list'])
def test_apt_uses_runner_ubuntu_sources_without_modifying_vendor_configuration(tmp_path, relative):
    source = tmp_path / relative
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text('runner Ubuntu archive')
    vendor = tmp_path / 'sources.list.d/vendor.list'
    vendor.parent.mkdir(parents=True, exist_ok=True)
    vendor.write_text('unrelated vendor archive')
    calls = []
    install(['xvfb', 'jq'], source_directory=tmp_path,
            runner=lambda command, **kwargs: calls.append(command))
    assert len(calls) == 2
    for command in calls:
        assert f'Dir::Etc::sourcelist={source}' in command
        assert 'Dir::Etc::sourceparts=-' in command
        assert 'Acquire::Retries=5' in command
        assert '--allow-unauthenticated' not in command
        assert Path(command[1]).name == 'retry.py'
    assert calls[0][-1] == 'update'
    assert calls[1][-4:] == ['install', '-y', 'xvfb', 'jq']
    assert vendor.read_text() == 'unrelated vendor archive'


def test_apt_fails_when_no_ubuntu_archive_is_configured(tmp_path):
    with pytest.raises(ValueError, match='Ubuntu archive configuration'):
        install(['xvfb'], source_directory=tmp_path,
                runner=lambda *args, **kwargs: pytest.fail('APT should not run'))
