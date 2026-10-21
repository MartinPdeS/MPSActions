# Release publication and recovery

Call `publish_release.yml` from a workflow triggered by a version tag. Enable
`documentation: true` to include documentation in the release:

```yaml
jobs:
  release:
    permissions:
      contents: write
      pages: write
      id-token: write
    uses: MartinPdeS/MPSActions/.github/workflows/publish_release.yml@v13
    with:
      documentation: true
      documentation_package_name: MyPackage
      documentation_python_version: "3.11"
      documentation_apt_package: xvfb
      download_retries: 3
      retry_delay_seconds: 10
      debug: true
      # Include the package's existing wheel and Conda inputs here.
    secrets:
      PYPI_API_TOKEN: ${{ secrets.PYPI_API_TOKEN }}
      ANACONDA_API_TOKEN: ${{ secrets.ANACONDA_API_TOKEN }}
```

The wheel matrix, Conda matrix, and documentation build run concurrently. All
must succeed before either registry upload begins. The documentation build
uploads an HTML artifact with its source commit and version. Only after **both**
registry uploads succeed does deployment publish that existing artifact. It
checks the artifact's commit and release tag before updating the site.

Branch and pull-request documentation workflows must omit tag triggers. Branch
builds may publish `latest` as development documentation; pull requests build
artifacts only. Versioned documentation is published through the release workflow.
Deployment is serialized across branch and release runs. Pages settings determine
whether the job uploads the site through GitHub Pages Actions or explicitly
requests a build of the configured documentation branch.

## Network retries

`download_retries` is the number of additional attempts, defaulting to three.
The delay grows from 10 to 20 to 30 seconds by default, capped at 60 seconds.
Retries require a recognized network error, such as a timeout, DNS failure,
connection reset, HTTP 429, or HTTP 5xx. Compiler errors, failed tests,
authentication errors, invalid package metadata, and dependency conflicts fail
immediately. Matrix `fail-fast` is disabled so one target does not cancel others.

The build environments also give pip and Conda five network retries and longer
connection timeouts. pip/uv retry settings are passed into cibuildwheel's Linux
containers and inherited by macOS and Windows builds. The Windows build continues
to run under PowerShell to preserve its native toolchain environment.

Uploads recheck the registry checksum after a failed request. If the upload
already completed, the job proceeds without sending it again. An identical
existing file is skipped on reruns; a different file with the same name fails.

## Logs and failed releases

The Actions console records source refs, runner/platform, Python/tool versions,
retry attempts, elapsed times, exit codes, and full build output. Artifact logs
are retained on successful and failed runs: `logs-wheels-*`, `logs-conda-*`,
`logs-wheels-pure*`, `logs-publication-*`, `documentation-build-log`, and
`documentation-deployment-log`. The release summary lists every stage's result.
No command-line secrets or complete environment dumps are added to diagnostics.

PyPI and Anaconda uploads cannot be atomic across registries. If one succeeds
and the other fails, documentation remains withheld. Use GitHub's **Re-run failed
jobs** to recover using the original verified artifacts. Rebuilding all artifacts
can change archive checksums even when the source is unchanged. A documentation
deployment failure can likewise be rerun without rebuilding or reuploading packages.

No new package release or tag is needed to retry an interrupted publication.
