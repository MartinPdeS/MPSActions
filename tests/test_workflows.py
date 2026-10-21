from pathlib import Path
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from lint_workflows import load, validate_interfaces


def workflow(name):
    return load(ROOT / '.github/workflows' / name)


def ancestors(jobs, name):
    result = set()
    needs = jobs[name].get('needs', [])
    if isinstance(needs, str):
        needs = [needs]
    for parent in needs:
        result.add(parent)
        result.update(ancestors(jobs, parent))
    return result


def test_both_registries_wait_for_all_builds_and_validation():
    jobs = workflow('publish_release.yml')['jobs']
    for publisher in ('publish_pypi', 'publish_conda'):
        assert {'pypi_pure', 'pypi_compiled', 'conda', 'validate'} <= ancestors(jobs, publisher)
        assert 'always()' not in jobs[publisher].get('if', '')
    assert 'secrets' not in jobs['pypi_pure']
    assert 'secrets' not in jobs['pypi_compiled']
    assert 'secrets' not in jobs['conda']


def test_only_publishing_jobs_receive_registry_credentials():
    for name in ('build_wheels.yml', 'build_conda_matrix.yml', 'build_conda_package.yml',
                 'build_pure_package.yml', 'validate_release.yml'):
        document = workflow(name)
        assert not document['on']['workflow_call'].get('secrets')
        assert 'API_TOKEN' not in (ROOT / '.github/workflows' / name).read_text()
    publisher = workflow('publish_distributions.yml')['jobs']['publish']
    assert publisher['if'] == "github.event_name == 'push' && startsWith(github.ref, 'refs/tags/')"
    assert publisher['concurrency']['cancel-in-progress'] is False
    assert 'id-token' not in workflow('publish_release.yml')['permissions']


def test_all_local_workflow_interfaces_resolve():
    validate_interfaces(ROOT)


def test_linter_rejects_unrecognized_workflow_inputs(tmp_path):
    directory = tmp_path / '.github/workflows'
    directory.mkdir(parents=True)
    (directory / 'called.yml').write_text("'on':\n  workflow_call:\n    inputs: {}\njobs: {}\n")
    (directory / 'caller.yml').write_text('jobs:\n  caller:\n    uses: ./.github/workflows/called.yml\n    with:\n      nonexistent: true\n')
    with pytest.raises(ValueError, match='unknown'):
        validate_interfaces(tmp_path)


def test_existing_public_inputs_and_tokens_are_preserved():
    release = workflow('publish_release.yml')['on']['workflow_call']
    assert {'pypi_python_version', 'pypi_build_linux', 'pypi_build_macos', 'pypi_build_windows',
            'pypi_package_type', 'pypi_project_directory', 'pypi_test_import', 'pypi_test_command',
            'pypi_apt_package', 'pypi_brew_package', 'pypi_mingw_package', 'conda_python_versions',
            'conda_os_list', 'conda_package_name', 'conda_recipe_path', 'conda_test_command',
            'conda_test_import', 'conda_channels', 'conda_upload_user'} <= set(release['inputs'])
    assert set(release['secrets']) == {'PYPI_API_TOKEN', 'ANACONDA_API_TOKEN'}


def test_integration_workflows_use_real_builds_without_publication():
    jobs = workflow('test_release_integration.yml')['jobs']
    assert jobs['pure']['strategy']['matrix']['python'] == ['3.11', '3.14']
    assert len(jobs['pure']['strategy']['matrix']['os']) == 3
    assert jobs['native_wheels']['uses'].endswith('build_wheels.yml')
    assert jobs['native_conda']['uses'].endswith('build_conda_matrix.yml')
    assert all('secrets' not in job for job in jobs.values())
    assert all('publish' not in job['uses'] for name, job in jobs.items() if name != 'documentation')
    assert jobs['documentation']['with']['deploy-pages'] is False


def test_conda_manifest_is_uploaded_with_archives():
    steps = workflow('build_conda_package.yml')['jobs']['build']['steps']
    artifact = next(step['with'] for step in steps if step.get('uses', '').startswith('actions/upload-artifact')
                    and step.get('if') != 'failure()')
    assert 'manifest-*.json' in artifact['path']


def test_shared_assets_are_not_downloaded_from_master():
    document = (ROOT / '.github/workflows/publish_documentation.yml').read_text()
    assert 'raw.githubusercontent.com' not in document
    assert 'inputs.debug' in document
    assert 'documentation-build-log' in document


def test_windows_quality_steps_use_bash():
    assert workflow('quality.yml')['defaults']['run']['shell'] == 'bash'
