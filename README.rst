MPSActions
==========

Reusable GitHub Actions workflows for building, testing, publishing, coverage,
and documentation deployments in MartinPdeS projects. The workflows are
called from consuming repositories; they do not run on MPSActions events.

Use a workflow
--------------

Use the ``v1`` release line for backward-compatible updates:

.. code-block:: yaml

   jobs:
     publish_conda:
       uses: MartinPdeS/MPSActions/.github/workflows/publish_compiled_package_to_anaconda.yml@v1
       with:
         package_name: example-package
         python_versions: '["3.11", "3.12", "3.13"]'
         os_list: '["ubuntu-latest", "macos-latest", "windows-latest"]'
         test_import: example_package
       secrets:
         ANACONDA_API_TOKEN: ${{ secrets.ANACONDA_API_TOKEN }}

For maximum supply-chain reproducibility, pin a full commit SHA instead. A
release tag such as ``v1.0.0`` is immutable; the ``v1`` tag advances only for
backward-compatible fixes and features.

Available workflows
-------------------

``build_conda_package.yml``
  Build a Conda package for one runner and Python version, install it into a
  clean prefix, optionally verify it, then upload the package artifact.

``publish_compiled_package_to_anaconda.yml``
  Matrix-build compiled Conda packages, verify each artifact before upload, and
  publish verified artifacts for tag pushes.

``publish_compiled_package_to_PyPi.yml``
  Build platform wheels through cibuildwheel and publish the collected wheels
  to PyPI after every selected platform succeeds.

``publish_pure_package_to_PyPi.yml``
  Run the source test suite, build a pure-Python wheel, optionally test that
  wheel in a fresh environment, and publish it for tag pushes.

``publish_coverage.yml``
  Install a project with its testing extra, run pytest with an optional coverage
  target, and post the coverage report.

``publish_documentation.yml``
  Build Sphinx documentation, maintain versioned and ``latest`` static sites,
  update the version switcher, and deploy GitHub Pages. Deployments for a
  repository are serialized so branch and tag builds cannot merge generated
  assets concurrently.

Key inputs
----------

Conda workflows accept ``package_name``, ``python_versions``, ``os_list``,
``conda_channels``, and optional platform package lists. ``test_import`` is a
legacy Python import smoke test. Prefer ``test_command`` for a command executed
from outside the source checkout in the clean Conda environment.

The pure-PyPI workflow accepts an optional ``test-command``. It runs after the
built wheel has been installed into a fresh virtual environment. Compiled-wheel
tests belong in the caller's cibuildwheel configuration.

Coverage accepts ``coverage-package`` when a project-specific coverage target
is desired. Documentation accepts ``source-ref`` and
``fail-on-sphinx-warning`` in addition to its package and Python settings.

Contributing
------------

Keep reusable-workflow inputs backward-compatible within a major release line.
Use explicit, immutable action references when practical, keep secrets scoped
to publishing jobs, and ensure artifact tests execute outside the source tree.

Before submitting a change, validate YAML and run actionlint if available:

.. code-block:: console

   actionlint .github/workflows/*.yml

When a change is suitable for all v1 consumers, advance the mutable ``v1`` tag
after it has been committed to ``master``. Create a new major tag for breaking
workflow-contract changes.
