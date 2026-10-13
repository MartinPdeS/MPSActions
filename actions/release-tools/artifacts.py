"""Create and verify release manifests; test exact Conda archives before upload."""
import argparse
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import zipfile

from retry import run as retry_download


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def normalized(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def conda_metadata(path):
    path = Path(path)
    if path.name.endswith(".tar.bz2"):
        with tarfile.open(path) as archive:
            stream = archive.extractfile("info/index.json")
            if stream is None:
                raise ValueError(f"missing Conda metadata: {path.name}")
            return json.load(stream)
    # conda-build installs conda-package-handling, including .conda support.
    from conda_package_handling.api import extract
    with tempfile.TemporaryDirectory() as temporary:
        extract(str(path.resolve()), temporary, components="info")
        return json.loads((Path(temporary) / "info/index.json").read_text())


def metadata(path):
    path = Path(path)
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(names) != 1:
                raise ValueError(f"invalid wheel metadata: {path.name}")
            record = BytesParser().parsebytes(archive.read(names[0]))
        tags = path.stem.rsplit("-", 3)[-3:]
        return {"name": record["Name"], "version": record["Version"],
                "python_tags": tags[0].split("."), "abi_tags": tags[1].split("."),
                "platform_tags": tags[2].split(".")}
    if path.name.endswith(".tar.gz"):
        with tarfile.open(path) as archive:
            names = [item for item in archive.getmembers()
                     if item.name.count("/") == 1 and item.name.endswith("/PKG-INFO")]
            if len(names) != 1:
                raise ValueError(f"invalid source distribution metadata: {path.name}")
            record = BytesParser().parsebytes(archive.extractfile(names[0]).read())
        return {"name": record["Name"], "version": record["Version"]}
    return conda_metadata(path)


def distributions(root, registry):
    patterns = ("*.whl", "*.tar.gz") if registry == "pypi" else ("*.conda", "*.tar.bz2")
    return sorted({path for pattern in patterns for path in Path(root).rglob(pattern)})


def wheel_matches(record, identifier):
    python, platform = identifier.split("-", 1)
    if python not in record.get("python_tags", ()):
        return False
    for tag in record.get("platform_tags", ()):
        if tag == platform:
            return True
        if platform.startswith("manylinux_") and tag.startswith("manylinux"):
            if tag.endswith("_" + platform.removeprefix("manylinux_")):
                return True
        if platform.startswith("macosx_") and tag.startswith("macosx_"):
            if tag.endswith("_" + platform.removeprefix("macosx_")):
                return True
    return False


def expected_version(ref):
    if not ref.startswith("refs/tags/"):
        return None
    tag = ref.removeprefix("refs/tags/").removeprefix("v")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?", tag):
        raise ValueError("release tags must use vMAJOR.MINOR.PATCH (optionally a/b/rc)")
    return tag


def write_manifest(root, registry, identity, expected=(), max_size_mb=500):
    root = Path(root)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", identity):
        raise ValueError("invalid artifact identity")
    paths = distributions(root, registry)
    if not paths:
        raise ValueError("no distributions were produced")
    records = []
    for path in paths:
        if path.stat().st_size > max_size_mb * 1024 * 1024:
            raise ValueError(f"artifact exceeds {max_size_mb} MiB: {path.name}")
        record = metadata(path)
        if not record.get("name") or not record.get("version"):
            raise ValueError("package name and version are required")
        record.update(path=path.relative_to(root).as_posix(), size=path.stat().st_size,
                      sha256=sha256(path))
        records.append(record)
    for identifier in expected:
        if not any(wheel_matches(record, identifier) for record in records):
            raise ValueError(f"missing wheel: {identifier}")
    manifest = {"schema": 1, "registry": registry, "identity": identity,
                "expected_wheels": list(expected), "files": records}
    output = root / f"manifest-{identity}.json"
    output.write_text(json.dumps(manifest, indent=2) + "\n")
    return output


def verify(root, registry, identities=None, ref="", package=None):
    root = Path(root).resolve()
    manifests = sorted(root.glob("manifest-*.json"))
    if not manifests:
        raise ValueError("no artifact manifests found")
    seen_identities, covered, records = set(), set(), []
    names, versions = set(), set()
    for manifest_path in manifests:
        manifest = json.loads(manifest_path.read_text())
        identity = manifest["identity"]
        if manifest.get("schema") != 1 or manifest["registry"] != registry:
            raise ValueError("manifest schema or registry mismatch")
        if identity in seen_identities:
            raise ValueError(f"duplicate manifest identity: {identity}")
        seen_identities.add(identity)
        if not manifest["files"]:
            raise ValueError("empty artifact manifest")
        for record in manifest["files"]:
            original_path = root / record["path"]
            path = original_path.resolve()
            if not path.is_relative_to(root) or path in covered or original_path.is_symlink():
                raise ValueError("unsafe or duplicate manifest path")
            if not path.is_file() or sha256(path) != record["sha256"]:
                raise ValueError(f"artifact checksum mismatch: {record['path']}")
            if path.stat().st_size != record["size"]:
                raise ValueError(f"artifact size mismatch: {record['path']}")
            actual = metadata(path)
            if any(record.get(key) != value for key, value in actual.items()):
                raise ValueError("artifact metadata does not match its manifest")
            names.add(normalized(actual["name"]))
            versions.add(actual["version"])
            covered.add(path)
            records.append(record)
        for identifier in manifest.get("expected_wheels", ()):
            if not any(wheel_matches(record, identifier) for record in manifest["files"]):
                raise ValueError(f"missing wheel: {identifier}")
    if identities is not None and seen_identities != set(identities):
        raise ValueError(f"artifact matrix incomplete: expected {sorted(identities)}, "
                         f"received {sorted(seen_identities)}")
    if covered != {path.resolve() for path in distributions(root, registry)}:
        raise ValueError("unmanifested release files found")
    if len(names) != 1 or len(versions) != 1:
        raise ValueError("release artifacts disagree on package name or version")
    if package and names != {normalized(package)}:
        raise ValueError("wrong package was built")
    version = expected_version(ref)
    if version and versions != {version}:
        raise ValueError(f"artifact version does not match release tag {version}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a") as output:
            output.write(f"### Verified {registry} distributions\n\n")
            output.write("| File | Version | SHA-256 |\n|---|---|---|\n")
            for record in records:
                output.write(f"| {record['path']} | {record['version']} | `{record['sha256']}` |\n")
    print(f"Verified {len(records)} {registry} distributions from {len(manifests)} builds.")
    return records


def install_conda(root, package, python, prefix, channels):
    candidates = [path for path in distributions(root, "conda")
                  if normalized(conda_metadata(path)["name"]) == normalized(package)]
    if len(candidates) != 1:
        raise ValueError(f"expected one local {package} archive, found {len(candidates)}")
    artifact = candidates[0].resolve()
    record = conda_metadata(artifact)
    # Resolve the archive's declared dependencies, then install that exact archive.
    # Installing by package name can select a previously published build instead.
    command = ["conda", "create", "-y", "-p", prefix, "--override-channels"]
    for channel in channels.split(","):
        if channel.strip():
            command += ["-c", channel.strip()]
    command += [f"python={python}", *record.get("depends", ())]
    status = retry_download(command, retries=int(os.environ.get("MPS_RETRIES", "3")),
                            delay=int(os.environ.get("MPS_RETRY_DELAY", "10")),
                            clean_prefix=prefix)
    if status:
        return status
    subprocess.run(["conda", "install", "-y", "-p", prefix, "--no-deps", str(artifact)], check=True)
    installed = json.loads(subprocess.check_output(
        ["conda", "list", "-p", prefix, "--json"], text=True))
    matches = [item for item in installed if normalized(item["name"]) == normalized(package)]
    if len(matches) != 1 or matches[0]["version"] != record["version"] or matches[0]["build_string"] != record["build"]:
        raise ValueError("installed Conda package does not match the built archive")
    print(f"Installed exact archive: {artifact.name}")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("manifest", "verify"):
        sub = commands.add_parser(command)
        sub.add_argument("--root", required=True)
        sub.add_argument("--registry", choices=("pypi", "conda"), required=True)
        if command == "manifest":
            sub.add_argument("--identity", required=True)
            sub.add_argument("--expected-file")
            sub.add_argument("--max-size-mb", type=int, default=500)
        else:
            sub.add_argument("--identities-json")
            sub.add_argument("--ref", default=os.environ.get("GITHUB_REF", ""))
            sub.add_argument("--package")
    sub = commands.add_parser("install-conda")
    for option in ("root", "package", "python", "prefix", "channels"):
        sub.add_argument("--" + option, required=True)
    arguments = parser.parse_args()
    if arguments.command == "manifest":
        expected = Path(arguments.expected_file).read_text().split() if arguments.expected_file else []
        print(write_manifest(arguments.root, arguments.registry, arguments.identity,
                             expected, arguments.max_size_mb))
    elif arguments.command == "verify":
        identities = json.loads(arguments.identities_json) if arguments.identities_json else None
        verify(arguments.root, arguments.registry, identities, arguments.ref, arguments.package)
    else:
        return install_conda(arguments.root, arguments.package, arguments.python,
                             arguments.prefix, arguments.channels)
    return 0


if __name__ == "__main__":
    sys.exit(main())
