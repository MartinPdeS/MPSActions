from pathlib import Path
import json
import os
import subprocess
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
    assert 'publish_documentation.yml@' in jobs['documentation']['uses']
    assert jobs['documentation']['with']['deploy-pages'] is False


def test_conda_manifest_is_uploaded_with_archives():
    steps = workflow('build_conda_package.yml')['jobs']['build']['steps']
    artifact = next(step['with'] for step in steps if step.get('uses', '').startswith('actions/upload-artifact')
                    and step.get('if') != 'failure()')
    assert 'manifest-*.json' in artifact['path']


def test_shared_assets_are_not_downloaded_from_master():
    document = (ROOT / '.github/workflows/build_documentation.yml').read_text()
    assert 'raw.githubusercontent.com' not in document
    assert 'inputs.debug' in document
    assert 'documentation-build-log' in document


def test_windows_quality_steps_use_bash():
    assert workflow('quality.yml')['defaults']['run']['shell'] == 'bash'


@pytest.mark.parametrize('pypi', ['success', 'failure', 'skipped', 'cancelled'])
@pytest.mark.parametrize('conda', ['success', 'failure', 'skipped', 'cancelled'])
@pytest.mark.parametrize('build', ['success', 'failure', 'skipped', 'cancelled'])
def test_documentation_deployment_requires_both_publications(pypi, conda, build):
    """Evaluate the deployed condition against every combination of job results."""
    jobs = workflow('publish_release.yml')['jobs']
    deployment = jobs['documentation_publish']
    assert set(deployment['needs']) == {'publish_pypi', 'publish_conda', 'documentation_build'}
    condition = deployment['if'].replace('!cancelled()', 'True').replace('inputs.documentation', 'True')
    for name, result in [('publish_pypi', pypi), ('publish_conda', conda), ('documentation_build', build)]:
        condition = condition.replace(f'needs.{name}.result', repr(result))
    condition = condition.replace('&&', ' and ')
    assert eval(condition, {'__builtins__': {}}) == (pypi == conda == build == 'success')
    assert '!cancelled()' in deployment['if']
    assert 'documentation_build' in ancestors(jobs, 'publish_pypi')
    assert 'documentation_build' in ancestors(jobs, 'publish_conda')
    assert deployment['uses'].endswith('deploy_documentation.yml')


def test_documentation_preview_is_read_only_and_deployment_reuses_html():
    build = workflow('build_documentation.yml')
    deploy = workflow('deploy_documentation.yml')
    assert build['permissions'] == {'contents': 'read'}
    assert 'git push' not in str(build)
    assert 'python -m sphinx' not in str(deploy)
    assert 'mps-documentation-source.json' in str(build)
    assert 'different source commit' in str(deploy)
    assert 'does not match the release tag' in str(deploy)
    assert deploy['jobs']['deploy']['if'] == "github.event_name == 'push'"
    assert deploy['jobs']['deploy']['concurrency']['cancel-in-progress'] is False


def test_native_build_retry_preserves_windows_powershell_and_matrix_completion():
    wheels = workflow('build_wheels.yml')['jobs']['build']
    assert wheels['strategy']['fail-fast'] is False
    windows = next(step for step in wheels['steps'] if step.get('name') == 'Build and test Windows wheels')
    assert windows['shell'] == 'pwsh'
    assert 'retry.py' in windows['run']
    assert '$LASTEXITCODE' in windows['run']
    conda = workflow('build_conda_package.yml')['jobs']['build']
    assert 'retry.py' in next(step['run'] for step in conda['steps'] if step.get('name') == 'Build package')


@pytest.mark.parametrize('source_sha,tag,branch_build,expected', [
    ('source-commit', 'v1.2.3', False, 0),
    ('other-commit', 'v1.2.3', False, 1),
    ('source-commit', 'v1.2.2', False, 1),
    ('source-commit', 'latest', True, 1),
])
def test_deployment_checks_actual_artifact_provenance(tmp_path, source_sha, tag, branch_build, expected):
    """Run the deployment's provenance script against real artifact files."""
    steps = workflow('deploy_documentation.yml')['jobs']['deploy']['steps']
    check = next(step['run'] for step in steps if step.get('name') == 'Verify documentation source and release version')
    script = check.split("python - <<'PYTHON'\n", 1)[1].rsplit('\nPYTHON', 1)[0]
    source = tmp_path / 'documentation-html'
    source.mkdir()
    (source / 'index.html').write_text('documentation')
    (source / 'mps-documentation-source.json').write_text(json.dumps({
        'sha': source_sha, 'tag': tag, 'branch_build': branch_build,
    }))
    env = dict(os.environ, RUNNER_TEMP=str(tmp_path), GITHUB_SHA='source-commit',
               GITHUB_REF='refs/tags/v1.2.3', GITHUB_ENV=str(tmp_path / 'job-environment'))
    result = subprocess.run([sys.executable, '-c', script], env=env, capture_output=True, text=True)
    assert result.returncode == expected, result.stderr
    if expected == 0:
        assert 'DOC_TAG=v1.2.3' in (tmp_path / 'job-environment').read_text()
    else:
        assert not (tmp_path / 'job-environment').exists()
