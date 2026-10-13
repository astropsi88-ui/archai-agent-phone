"""Private backup to a NEW directory, SQLite online backup, receipt SHA256."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3


def backup(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination == source or source in destination.parents:
        raise ValueError('Backup must be outside the data directory')
    names = ['owner-password.hash', 'edge.sqlite3']
    if not all((source / name).is_file() for name in names):
        raise ValueError('Missing initialized data; start the app once first')
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name in names[:1]:
        shutil.copyfile(source / name, destination / name)
        os.chmod(destination / name, 0o600)
    with closing(sqlite3.connect((source / 'edge.sqlite3').as_uri() + '?mode=ro', uri=True)) as src:
        with closing(sqlite3.connect(destination / 'edge.sqlite3')) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Backup SQLite integrity failed')
    os.chmod(destination / 'edge.sqlite3', 0o600)
    receipt = {name: {'sha256': hashlib.sha256((destination / name).read_bytes()).hexdigest(),
                      'bytes': (destination / name).stat().st_size} for name in names}
    (destination / 'receipt.json').write_text(json.dumps(receipt, indent=2))
    return receipt


def verify(destination):
    destination = Path(destination)
    receipt = json.loads((destination / 'receipt.json').read_text())
    if set(receipt) != {'owner-password.hash', 'edge.sqlite3'}:
        raise ValueError('Invalid receipt allowlist')
    for name, entry in receipt.items():
        data = (destination / name).read_bytes()
        if len(data) != entry['bytes'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise ValueError('Backup checksum mismatch')
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('destination')
    parser.add_argument('--data-dir', default=os.environ.get('DATA_DIR', str(Path(__file__).resolve().parent / 'data')))
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    if args.verify:
        verify(args.destination)
        print('Backup checksum verified')
    else:
        backup(args.data_dir, args.destination)
        verify(args.destination)
        print('Private backup created and checksum verified; never publish it')


if __name__ == '__main__':
    main()
