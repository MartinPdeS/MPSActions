"""Maintain versioned documentation without replacing latest with older releases."""
import argparse
import html
import json
from pathlib import Path
import re
import shutil


def version_key(tag):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:(a|b|rc)(\d+))?", tag)
    if not match:
        raise ValueError(f"unsupported version directory: {tag}")
    major, minor, patch, stage, number = match.groups()
    return (int(major), int(minor), int(patch),
            {"a": 0, "b": 1, "rc": 2, None: 3}[stage], int(number or 0))


def render_landing(template, base_url):
    encoded = json.dumps(base_url.rstrip('/')).replace('<', '\\u003c').replace('>', '\\u003e')
    return template.replace('<base-url-json>', encoded).replace(
        '<base-url-html>', html.escape(base_url.rstrip('/'), quote=True))


def update(source, root, tag, base_url, branch_build=False, template=None, retain_versions=0):
    if retain_versions < 0:
        raise ValueError('retain_versions must be nonnegative')
    source, root = Path(source), Path(root)
    if not (source / "index.html").is_file():
        raise ValueError("documentation build has no index.html")
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    versions = [path.name for path in docs.iterdir()
                if path.is_dir() and re.fullmatch(r"v?\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?", path.name)]
    if not branch_build:
        key = version_key(tag)
        target = docs / tag
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(source, target)
        versions = list(set(versions + [tag]))
    else:
        key = None
    latest = docs / "latest"
    # Older tag builds must not roll back the documentation users see by default.
    if branch_build or key == max(map(version_key, versions), default=key):
        shutil.rmtree(latest, ignore_errors=True)
        shutil.copytree(source, latest)
    if retain_versions:
        ordered = sorted(versions, key=version_key, reverse=True)
        for version in ordered[retain_versions:]:
            print(f'Removing retained documentation version: {version}')
            shutil.rmtree(docs / version)
        versions = ordered[:retain_versions]
    entries = []
    if latest.is_dir():
        entries.append({"name": "latest", "version": "latest",
                        "url": f"{base_url.rstrip('/')}/docs/latest"})
    for version in sorted(versions, key=version_key, reverse=True):
        entries.append({"name": version, "version": version,
                        "url": f"{base_url.rstrip('/')}/docs/{version}"})
    (root / "version_switcher.json").write_text(json.dumps(entries, indent=2) + "\n")
    (root / ".nojekyll").touch()
    if template is not None:
        (root / "index.html").write_text(render_landing(Path(template).read_text(), base_url))
    print(f"Documentation versions: {', '.join(entry['name'] for entry in entries)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("source", "root", "tag", "base-url"):
        parser.add_argument("--" + option, required=True)
    parser.add_argument("--branch-build", action="store_true")
    parser.add_argument("--template")
    parser.add_argument("--retain-versions", type=int, default=0)
    args = parser.parse_args()
    update(args.source, args.root, args.tag, args.base_url, args.branch_build, args.template, args.retain_versions)


if __name__ == "__main__":
    main()
