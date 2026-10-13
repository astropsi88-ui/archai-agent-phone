"""Initialize ONLY edge login; never agent personality/memory/history."""
import argparse
import getpass
import os
from pathlib import Path
from server import password_hash

def initialize(data,phrase):
    if not 12<=len(phrase)<=256:raise ValueError('Choose 12 to 256 characters')
    data=Path(data);data.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (data/'owner-password.hash').open('x') as f:f.write(password_hash(phrase)+'\n')
    os.chmod(data/'owner-password.hash',0o600)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data-dir',default=os.environ.get('DATA_DIR',str(Path(__file__).parent/'data')));a=p.parse_args();os.umask(0o077)
    phrase=getpass.getpass('New local owner phrase: ')
    if phrase!=getpass.getpass('Repeat: '):raise SystemExit('Phrases differ')
    initialize(a.data_dir,phrase);print('Local owner login initialized; existing agent untouched.')
