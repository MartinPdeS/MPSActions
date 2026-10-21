"""Install Ubuntu build dependencies without refreshing unrelated vendor repositories."""

import argparse
from pathlib import Path
import subprocess
import sys


def install(packages, source_directory=Path('/etc/apt'), runner=subprocess.run):
    """Refresh the runner's Ubuntu archive and install the requested packages."""
    sources = [source_directory / 'sources.list.d/ubuntu.sources', source_directory / 'sources.list']
    source = next((path for path in sources if path.is_file()), None)
    if source is None:
        raise ValueError('Cannot find the runner Ubuntu archive configuration.')
    print(f'Ubuntu APT sources: {source}', flush=True)
    print(f'Requested Ubuntu packages: {", ".join(packages)}', flush=True)
    apt = ['sudo', 'apt-get', '-o', f'Dir::Etc::sourcelist={source}',
           '-o', 'Dir::Etc::sourceparts=-', '-o', 'Acquire::Retries=5']
    retry = str(Path(__file__).with_name('retry.py'))
    for label, arguments in [('Ubuntu package index', ['update']),
                             ('Ubuntu dependency installation', ['install', '-y', *packages])]:
        runner([sys.executable, retry, '--label', label, '--', *apt, *arguments], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('packages', nargs='+')
    install(parser.parse_args().packages)


if __name__ == '__main__':
    main()
