"""Run with python3 -m backend.main from the repository root."""

import argparse

from .classifier import ClassifiedDirectionSource, ThresholdClassifier
from .models import DirectionSource
from .simulator import KeyboardSampleSource, keyboard_input


def print_directions(source: DirectionSource) -> None:
    """Consume the common event interface, independent of acquisition hardware."""
    while (event := source.read_event()) is not None:
        print(event.direction.value, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Keyboard directions, raw Nano acquisition, or CSV replay.")
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--horizontal-polarity", type=int, choices=(-1, 1), default=1)
    parser.add_argument("--vertical-polarity", type=int, choices=(-1, 1), default=1)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--serial-port", help="Read raw Nano R4 ADC counts instead of keyboard directions")
    modes.add_argument("--replay", help="Replay a raw ADC recording without hardware")
    parser.add_argument("--record", help="Save live ADC readings to a new CSV file")
    parser.add_argument("--realtime", action="store_true", help="Pace replay using recorded receipt timestamps")
    parser.add_argument("--count", type=int, help="Stop serial/replay mode after this many samples")
    args = parser.parse_args()
    if args.count is not None and (args.count <= 0 or not (args.serial_port or args.replay)):
        parser.error("--count must be positive and used with --serial-port or --replay")
    if args.record and not args.serial_port:
        parser.error("--record requires --serial-port")
    if args.realtime and not args.replay:
        parser.error("--realtime requires --replay")
    if args.replay:
        from .recording import print_replay

        try:
            print_replay(args.replay, args.realtime, args.count)
        except KeyboardInterrupt:
            pass
        except (ValueError, OSError) as error:
            raise SystemExit(str(error)) from error
        return
    if args.serial_port:
        from .serial_input import print_serial_samples

        try:
            print_serial_samples(args.serial_port, args.count, args.record)
        except KeyboardInterrupt:
            pass
        except (ValueError, TimeoutError, OSError) as error:
            raise SystemExit(str(error)) from error
        return
    try:
        classifier = ThresholdClassifier(
            args.threshold, args.horizontal_polarity, args.vertical_polarity
        )
    except ValueError as error:
        parser.error(str(error))
    print("Arrow keys / WASD: direction | Space / C: CENTER | Q / Ctrl-C: quit")
    try:
        with keyboard_input() as stream:
            print_directions(ClassifiedDirectionSource(KeyboardSampleSource(stream), classifier))
    except KeyboardInterrupt:
        pass
    except ValueError as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
