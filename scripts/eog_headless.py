"""Serial or CSV input to versioned EOG JSON Lines. Never plays speech or drives HUD."""
import argparse
from contextlib import ExitStack
import json
import sys
from backend.eog_pipeline import EOGPipeline, SLOTS
from backend.eog_waveform import WaveformProfile
from backend.guided_eog import GuidedConfig
from backend.recording import CSVReplaySource
from backend.serial_input import SerialADCSource


def main():
    p=argparse.ArgumentParser(description=__doc__)
    modes=p.add_mutually_exclusive_group(required=True)
    modes.add_argument('--csv');modes.add_argument('--serial-port')
    p.add_argument('--profile',required=True);p.add_argument('--communication',action='store_true')
    p.add_argument('--pulse-confirmation',action='store_true')
    p.add_argument('--return-guard',action='store_true')
    args=p.parse_args()
    pipeline=EOGPipeline(WaveformProfile.load(args.profile),GuidedConfig(pulse_confirmation=args.pulse_confirmation,excursion_guard=args.return_guard))
    pipeline.set_choices({slot:dict(id=f'slot:{slot}',label=direction,enabled=True) for direction,slot in SLOTS.items()},0)
    previous=None
    try:
        with ExitStack() as stack:
            if args.csv:source=CSVReplaySource(stack.enter_context(open(args.csv,newline='')))
            else:
                import serial
                source=SerialADCSource(stack.enter_context(serial.Serial(args.serial_port,115200,timeout=.5,exclusive=True)))
            while (sample:=source.read_sample()) is not None:
                result=pipeline.process(sample.horizontal,sample.vertical,sample.timestamp_ms,communication=args.communication)
                for event in result['events']:print(json.dumps(dict(kind='event',**event),allow_nan=False),flush=True)
                state=result['state'];signature=(state['phase'],state['reason'],state['pending'],state['armed'],state['confirmation'])
                if signature!=previous:
                    print(json.dumps(dict(kind='state',**state),allow_nan=False),flush=True);previous=signature
    except KeyboardInterrupt:pass
    except (OSError,ValueError,TimeoutError) as error:
        pipeline.fault(type(error).__name__)
        for event in pipeline.pending_events:print(json.dumps(dict(kind='event',**event)),flush=True)
        print(str(error),file=sys.stderr);return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
