"""Non-destructive readiness report; never uploads or opens a serial port."""

import importlib.util
import json
import platform
import sys


def main():
    report = dict(python=sys.version.split()[0], machine=platform.machine(), os=platform.system(),
                  python_supported=sys.version_info >= (3, 10),
                  pyserial=importlib.util.find_spec("serial") is not None,
                  pillow=importlib.util.find_spec("PIL") is not None)
    try:
        from serial.tools.list_ports import comports
        report["ports"] = [dict(device=p.device, description=p.description) for p in comports()]
    except ImportError:
        report["ports"] = []
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
