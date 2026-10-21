import json

import pytest

from docs import update, version_key


def test_older_release_cannot_replace_latest(tmp_path):
    source, site = tmp_path / 'source', tmp_path / 'site'
    source.mkdir()
    (source / 'index.html').write_text('new release')
    update(source, site, 'v2.0.0', 'https://example.test/project')
    (source / 'index.html').write_text('old release')
    update(source, site, 'v1.9.0', 'https://example.test/project')
    assert (site / 'docs/latest/index.html').read_text() == 'new release'
    assert (site / 'docs/v1.9.0/index.html').read_text() == 'old release'
    entries = json.loads((site / 'version_switcher.json').read_text())
    assert [item['version'] for item in entries] == ['latest', 'v2.0.0', 'v1.9.0']


def test_branch_build_does_not_overwrite_versioned_release(tmp_path):
    source, site = tmp_path / 'source', tmp_path / 'site'
    source.mkdir()
    (source / 'index.html').write_text('release')
    update(source, site, 'v1.0.0', 'https://example.test')
    (source / 'index.html').write_text('development')
    update(source, site, 'latest', 'https://example.test', branch_build=True)
    assert (site / 'docs/v1.0.0/index.html').read_text() == 'release'
    assert (site / 'docs/latest/index.html').read_text() == 'development'


def test_numeric_and_prerelease_version_ordering():
    assert version_key('v1.10.0') > version_key('v1.9.0')
    assert version_key('v2.0.0') > version_key('v2.0.0rc1') > version_key('v2.0.0b2')
    with pytest.raises(ValueError):
        version_key('../escape')


def test_landing_page_uses_callers_url(tmp_path):
    from pathlib import Path
    from docs import render_landing
    template = (Path(__file__).resolve().parents[1] / 'asset/template_index.html').read_text()
    rendered = render_landing(template, 'https://example.test/custom')
    assert 'https://example.test/custom/docs/latest/index.html' in rendered
    assert 'const baseUrl = "https://example.test/custom";' in rendered
    assert 'martinpdes' not in rendered
    assert '<base-url-' not in rendered


def test_retention_removes_old_versions_and_switcher_entries(tmp_path):
    source, site = tmp_path / 'source', tmp_path / 'site'
    source.mkdir()
    (source / 'index.html').write_text('documentation')
    for tag in ('v1.9.0', 'v1.10.0', 'v2.0.0'):
        update(source, site, tag, 'https://example.test', retain_versions=2)
    assert not (site / 'docs/v1.9.0').exists()
    assert (site / 'docs/latest/index.html').exists()
    entries = json.loads((site / 'version_switcher.json').read_text())
    assert [entry['version'] for entry in entries] == ['latest', 'v2.0.0', 'v1.10.0']
