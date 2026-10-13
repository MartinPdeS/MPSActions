MPSActions
==========

Reusable GitHub Actions workflows for Python package builds, tests, releases,
coverage, and versioned documentation. Existing PyPI and Anaconda API tokens
remain supported; no Trusted Publishing setup or token rotation is required.

Release pipeline
----------------

The combined release workflow follows this sequence::

   plan --> wheel builds ------> validate all artifacts --> PyPI upload
        \-> Conda builds -----/                       \--> Anaconda upload

Neither registry uploads until every requested build and its installed-package
verification succeeds. Each build produces a uniquely named JSON manifest with
package metadata, file sizes, SHA-256 checksums, and expected wheel targets.
The common gate checks the complete matrix and version consistency. Publishing
jobs recheck the artifacts immediately before upload.

Uploads to two independent registries are not atomic: a registry outage can
still interrupt publication after the other upload succeeds. Rerun the failed
publishing job. Identical remote files are skipped after checksum comparison;
a different existing file is rejected. Published files are never force-replaced.

Use the combined release workflow
--------------------------------

Select a released commit SHA after the integration checks pass. The following
example uses a placeholder that must be replaced with that SHA:

.. code-block:: yaml

   permissions:
     contents: read

   jobs:
     release:
       uses: MartinPdeS/MPSActions/.github/workflows/publish_release.yml@<release-sha>
       with:
         pypi_python_version: "3.11"
         pypi_build_linux: true
         pypi_build_macos: true
         pypi_build_windows: true
         pypi_macos_install_gcc: false
         pypi_macos_install_fortran: false
         conda_python_versions: '["3.11", "3.12", "3.13", "3.14"]'
         conda_os_list: '["ubuntu-latest", "macos-latest", "windows-latest"]'
         conda_package_name: example-package
         conda_recipe_path: conda.recipe
         conda_test_command: python -c "import example_package"
         download_retries: 3
         retry_delay_seconds: 10
       secrets:
         PYPI_API_TOKEN: ${{ secrets.PYPI_API_TOKEN }}
         ANACONDA_API_TOKEN: ${{ secrets.ANACONDA_API_TOKEN }}

Tokens are forwarded only to publishing jobs. They are not passed to builds,
artifact verification, or integration tests. Uploads require a tag-push event;
branch and pull-request calls only build and validate. Release tags must match
the artifact version: ``vMAJOR.MINOR.PATCH`` or an ``a``, ``b``, or ``rc`` suffix.

Version consistency
-------------------

Internal workflow calls use relative references, resolving to the same commit
as the calling reusable workflow. The shared release-tools action uses GitHub's
``$/`` self-repository reference, which also follows the executing workflow's
commit even when it is called from another repository. Documentation templates
come from that revision rather than downloading ``master``.

The self-repository action syntax requires GitHub.com and runner 2.336.0 or
newer. See the `GitHub announcement <https://github.blog/changelog/2026-07-30-reference-same-repository-actions-with-self-repository-syntax/>`_.

Full commit SHAs provide reproducible consumer references. Use semantic release
tags for new releases; immutable version tags are never moved. This refactor is
prepared for the next release line and does not update existing consumer tags.

Available workflows
-------------------

``publish_release.yml``
  Build native wheels and Conda packages, validate both registries together,
  then publish with the caller's API tokens.

``build_wheels.yml``
  Build and test native wheels without registry credentials. Uses the caller's
  cibuildwheel configuration and checks that every selected build identifier
  has a corresponding wheel. Platform choices and toolchains are configurable.

``build_conda_matrix.yml`` and ``build_conda_package.yml``
  Build a matrix or one Conda package. Build-tools Python is independent of the
  target Python. Resolve the built archive's declared dependencies in a clean
  environment, install that exact local archive, then run the caller's command
  outside the source checkout. ``test_command`` or ``test_import`` is required.

``build_pure_package.yml``
  Run source tests, build a wheel and sdist, then test the installed wheel in a
  fresh environment. Prefer an explicit ``test_command``; ``test_import`` or
  the normalized distribution name provides an import smoke test otherwise.

``validate_release.yml`` and ``publish_distributions.yml``
  Validate a complete artifact matrix and publish verified distributions.
  The combined release workflow supplies the expected artifact identities.

``publish_compiled_package_to_PyPi.yml``,
``publish_compiled_package_to_anaconda.yml``, and
``publish_pure_package_to_PyPi.yml``
  Standalone publishing entrypoints. Existing input names and token names are
  preserved. They use the same build, verification, and publishing components.

``publish_documentation.yml``
  Build Sphinx documentation once, then update the documentation branch.
  Branch builds update ``latest``; tag builds create an immutable version
  directory. Older tag builds do not replace newer versioned ``latest`` docs.
  ``deploy-pages: false`` builds documentation without changing the branch.

``publish_coverage.yml``
  Run the caller's tests with coverage and post the existing coverage report.

Configuration
-------------

New build interfaces use snake_case inputs. Existing entrypoints retain their
original spelling, including ``python-version`` and ``build-Linux`` in the
standalone PyPI workflow. Do not rename those caller inputs during adoption.

Common controls:

* ``download_retries`` defaults to three additional attempts (four total).
  ``retry_delay_seconds`` defaults to 10: delays are 10, 20, and 30 seconds.
  Only recognizable network failures are retried. Authentication, dependency
  solving, compilation, and test failures fail without automatic retries.
* ``debug`` defaults to false. Jobs produce compact summaries and preserve
  wheel, Conda, or Sphinx build logs when appropriate.
* Conda supports ``tools_python_version`` (default 3.11),
  ``conda_build_version`` (default ``<26``), and ``miniforge_version``.
  The combined entrypoint prefixes the first and last with ``conda_``.
* Native-wheel builds support ``linux_runner``, ``macos_runner``,
  ``windows_runner``, ``macos_deployment_target``, ``xcode_version``,
  ``macos_install_gcc``, ``macos_install_fortran``, and
  ``cibuildwheel_version``. The combined entrypoint prefixes these with
  ``pypi_``. An empty Xcode version uses the runner's selected toolchain.
* Existing publishing entrypoints retain their GCC, Fortran, and macOS 26.0
  defaults. Disable unnecessary toolchains and select a lower deployment
  target only after testing the package's native dependency requirements.
  The new ``build_wheels.yml`` defaults to no extra toolchains and macOS 14.0.
* ``apt_package``, ``brew_package``, and ``mingw_package`` accept package lists.
  Commands and package lists are trusted workflow configuration, not event
  text supplied by untrusted users.
* ``pypi_package_name`` can override the expected PyPI distribution name when
  it differs from ``conda_package_name``.
* ``test_import`` is retained for existing Conda callers. Prefer
  ``test_command`` for a meaningful installed-package test. Wheel tests belong
  in the caller's cibuildwheel configuration and should run outside checkout.
* ``project_directory`` defaults to ``.`` in the new build workflows and docs.
  The legacy standalone compiled-PyPI input is ``project-directory``.
* Documentation supports ``source-ref``, ``fail-on-sphinx-warning``,
  ``documentation_branch`` (default ``documentation_page``), and ``base_url``.
  The default URL is derived from the calling repository's owner and name.
  Deployment requires ``contents: write`` in the calling workflow; build-only
  documentation checks need only ``contents: read``.

Shared Python CI setup
----------------------

``actions/setup-python`` checks out the caller, selects Python, and installs
its CI dependencies. Keep test commands in the calling workflow:

.. code-block:: yaml

   steps:
     - uses: MartinPdeS/MPSActions/actions/setup-python@<release-sha>
       with:
         python-version: "3.14"
         install-command: python -m pip install -e ".[testing]"
     - run: python -m pytest

Optional inputs control checkout history, submodules, and setup-python caches.
The composite action's smoke tests cover Linux, macOS, Windows, and propagation
of installation failures.

Contributing and verification
-----------------------------

.. code-block:: console

   python -m pip install "pytest>=8,<10" "PyYAML>=6,<7" "conda-package-handling>=2.4,<3"
   python -m pytest tests --ignore=tests/fixtures -q
   python tools/lint_workflows.py
   git diff --check

Install actionlint and ShellCheck before running the lint helper. Actionlint
1.7.12 predates ``$/`` references: the helper checks that interface itself and
excludes only actionlint's exact false positive for the release-tools action.
Other workflow and ShellCheck errors still fail CI.

The quality workflow tests retries, integrity checks, publishing safety,
documentation version selection, and reusable-workflow contracts on Python
3.11 and 3.14 across all three operating systems. Integration CI builds actual
pure and native fixture packages, tests native wheels and Conda archives, and
builds Sphinx documentation. Integration jobs have no registry tokens and do
not publish. Require these checks before releasing a new workflow revision.
