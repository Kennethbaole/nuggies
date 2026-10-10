"""Start a recorded guided EOG session with a private frozen profile; no automatic test start."""
import argparse
from datetime import datetime,timezone
from pathlib import Path
import shlex
import subprocess
import sys

from backend.eog_waveform import WaveformProfile

ROOT=Path(__file__).resolve().parents[1]


def choose_port(ports):
    candidates=[p.device for p in ports if 'nano' in (p.description or '').lower()]
    if not candidates:
        candidates=[p.device for p in ports if 'arduino' in (p.manufacturer or '').lower()]
    if len(candidates)!=1:
        raise ValueError('Connect the Nano, or pass --serial-port explicitly. No unique Nano/Arduino port was found.')
    return candidates[0]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--serial-port')
    p.add_argument('--port',type=int,default=8878,help='Local webpage port')
    p.add_argument('--profile',default=str(ROOT/'recordings/guided-runtime-selected/candidate-profile.json'))
    p.add_argument('--dry-run',action='store_true',help='Validate and print the command without opening a device')
    args=p.parse_args()
    try:
        WaveformProfile.load(args.profile)
        if args.serial_port:device=args.serial_port
        else:
            from serial.tools.list_ports import comports
            device=choose_port(comports())
    except (ValueError,OSError,ImportError) as error:p.error(str(error))
    folder=ROOT/'recordings';folder.mkdir(exist_ok=True)
    session=folder/('live-eog-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    command=[sys.executable,'-m','backend.app','--serial-port',device,'--port',str(args.port),
             '--eog-profile',str(Path(args.profile).resolve()),'--record',str(session)+'.csv',
             '--eog-log',str(session)+'.events.jsonl']
    print(shlex.join(command),flush=True)
    print(f'Open http://127.0.0.1:{args.port}, start the eye test, and wait for Ready.',flush=True)
    if not args.dry_run:
        try:raise SystemExit(subprocess.call(command,cwd=ROOT))
        except KeyboardInterrupt:raise SystemExit(130)


if __name__=='__main__':main()
