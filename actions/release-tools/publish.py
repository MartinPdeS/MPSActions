"""Publish verified files with API tokens; skip only identical existing files."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen

from artifacts import distributions, metadata, sha256, verify


def fetch(url, digest=False, opener=urlopen, sleep=time.sleep):
    retries = int(os.environ.get('MPS_RETRIES', '3'))
    delay = int(os.environ.get('MPS_RETRY_DELAY', '10'))
    for attempt in range(retries + 1):
        try:
            with opener(url, timeout=60) as response:
                if not digest:
                    return json.load(response)
                checksum = hashlib.sha256()
                for chunk in iter(lambda: response.read(1024 * 1024), b''):
                    checksum.update(chunk)
                return checksum.hexdigest()
        except HTTPError as error:
            if error.code == 404:
                return None
            if error.code not in (429, 500, 502, 503, 504) or attempt == retries:
                raise
        except (URLError, TimeoutError):
            if attempt == retries:
                raise
        sleep(min(delay * (attempt + 1), 60))
    raise AssertionError('unreachable')


def existing_digest(path, registry, user, fetcher=fetch):
    record = metadata(path)
    if registry == 'pypi':
        url = f"https://pypi.org/pypi/{quote(record['name'], safe='')}/{quote(record['version'], safe='')}/json"
        result = fetcher(url)
        if result is None:
            return None
        matches = [item for item in result['urls'] if item['filename'] == path.name]
        return matches[0]['digests']['sha256'] if matches else None
    subdir = record.get('subdir')
    if not subdir:
        raise ValueError('Conda package metadata must include its subdir')
    fields = (user, record['name'], record['version'], subdir, path.name)
    url = 'https://api.anaconda.org/download/' + '/'.join(quote(value, safe='') for value in fields)
    return fetcher(url, digest=True)


def publish(root, registry, identities, user='martinpdes', remote=existing_digest,
            runner=subprocess.run):
    verify(root, registry, identities, os.environ.get('GITHUB_REF', ''))
    secret = 'TWINE_PASSWORD' if registry == 'pypi' else 'ANACONDA_API_TOKEN'
    if not os.environ.get(secret):
        raise ValueError(f'{secret} is required for publication')
    paths = distributions(root, registry)
    if registry == 'pypi':
        runner(['python', '-m', 'twine', 'check', *map(str, paths)], check=True)
    for path in paths:
        checksum = remote(path, registry, user)
        if checksum is not None:
            if checksum != sha256(path):
                raise ValueError(f'refusing to replace a different published file: {path.name}')
            print(f'Already published with identical checksum: {path.name}')
            continue
        if registry == 'pypi':
            command = ['python', '-m', 'twine', 'upload', '--non-interactive', str(path)]
        else:
            command = ['conda', 'run', '-n', 'base', 'anaconda', '--token',
                       os.environ['ANACONDA_API_TOKEN'], 'upload', '--user', user, str(path)]
        # An ambiguous upload failure is resolved by re-running this job: remote
        # checksums distinguish a completed upload from a file still to publish.
        # Never force-overwrite an existing release.
        result = runner(command, check=False)
        if result.returncode:
            raise RuntimeError(f'Upload failed for {path.name} (exit {result.returncode}); '
                               'rerun the publish job to check whether it completed.')
        print(f'Published: {path.name}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--registry', choices=('pypi', 'conda'), required=True)
    parser.add_argument('--identities-json', required=True)
    parser.add_argument('--user', default='martinpdes')
    args = parser.parse_args()
    publish(args.root, args.registry, json.loads(args.identities_json), args.user)


if __name__ == '__main__':
    main()
