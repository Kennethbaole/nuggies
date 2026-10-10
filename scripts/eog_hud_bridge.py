"""Forward diagnostic status only to the existing ESP32 OLED T: protocol.

Use the ESP32's separate port, never the Nano acquisition port. This adapter
sends no highlight, selection or option commands and does not flash firmware.
"""
import argparse
import json
import os
import time
from urllib.request import Request, urlopen
from urllib.error import URLError

from backend.envfile import load_env


def status_text(state):
    if not state.get('wheel_test'):return 'Eye test off'
    if not state.get('connected'):return '! Signal paused'
    gaze=state.get('gaze_hover') or {}
    phase=gaze.get('phase')
    if phase=='centering':return 'Look center: setup'
    if phase=='retry':return '! Look center / Retry'
    if phase=='signal_lost':return '! Check connection'
    if phase=='recovery':return f"{(gaze.get('direction') or 'Gaze').capitalize()}: return center"[:23]
    if phase=='ready':return 'Ready: look then center'
    return 'Eye test: diagnostic'


def main():
    load_env()
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',required=True,help='Separate ESP32 OLED serial port, not Nano')
    p.add_argument('--url',default='http://127.0.0.1:8765')
    p.add_argument('--once',action='store_true',help='Send one status frame then exit')
    args=p.parse_args()
    import serial
    token=os.environ.get('APP_TOKEN','')
    headers={'Authorization':f'Bearer {token}'} if token else {}
    with serial.Serial(args.port,115200,timeout=.5,exclusive=True) as connection:
        # Let the ESP32 finish any reset caused by opening USB serial.
        time.sleep(2)
        try:
            while True:
                try:
                    with urlopen(Request(args.url.rstrip('/')+'/api/state',headers=headers),timeout=2) as response:
                        text=status_text(json.load(response))
                except (URLError,ValueError,TimeoutError):text='! Companion unavailable'
                connection.write(('T:'+text+'\n').encode('ascii'));connection.flush()
                if args.once:break
                time.sleep(.5) # Existing firmware expires status after 1.5s.
        except KeyboardInterrupt:pass


if __name__=='__main__':main()
