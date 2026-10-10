"""Start the companion app and Qwen speech-to-text with one command.

    python -m scripts.dev                       # app + local Qwen (if needed)
    python -m scripts.dev --no-asr              # app only
    python -m scripts.dev --serial-port COM5    # extra arguments go to backend.app

Both run as hidden background processes; their output appears here with an
[app] / [asr] prefix. Ctrl+C or closing this terminal stops both. Works on Windows, macOS, Linux and
the Jetson. Qwen is started locally only when ASR_URL points at this machine and
nothing answers there yet; if a tunnel or the Jetson already answers, that is
used instead. The two-process setup is unchanged; this only launches it.
"""

import argparse
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from backend.envfile import load_env
from backend.transcribe import RemoteTranscriber, TranscriptionUnavailable

ROOT = Path(__file__).resolve().parents[1]
LOOPBACK = ("127.0.0.1", "localhost", "::1")


def asr_python():
    venv = ROOT / ".venv-asr"
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def plan_asr(url, answering, no_asr=False):
    """Decide what to do about Qwen: 'off', 'existing', 'local' or 'unreachable'."""
    if no_asr or not url:
        return "off"
    if answering:
        return "existing"
    return "local" if urlsplit(url).hostname in LOOPBACK else "unreachable"


def answering(client):
    try:
        client.health()
        return True
    except TranscriptionUnavailable:
        return False


_job = None


def die_with_launcher(process):
    """Windows: put the child in a job the OS kills when this launcher exits, so
    closing the terminal never leaves hidden servers holding their ports."""
    import ctypes
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class Extended(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", ctypes.c_uint64 * 6),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    global _job
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    if _job is None:
        _job = kernel32.CreateJobObjectW(None, None)
        info = Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not _job or not kernel32.SetInformationJobObject(
                wintypes.HANDLE(_job), 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError(ctypes.get_last_error(), "could not create a job object")
    if not kernel32.AssignProcessToJobObject(wintypes.HANDLE(_job), wintypes.HANDLE(int(process._handle))):
        raise OSError(ctypes.get_last_error(), "could not tie the server to this launcher")


def start(name, command):
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    # Windows: no console window. Elsewhere the children share this terminal's process
    # group, so Ctrl+C and closing the terminal reach them as well.
    hidden = dict(creationflags=subprocess.CREATE_NO_WINDOW) if os.name == "nt" else {}
    process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", **hidden)
    if os.name == "nt":
        try:
            die_with_launcher(process)
        except OSError:
            process.kill()
            raise

    def relay():
        for line in process.stdout:
            print(f"[{name}] {line.rstrip()}", flush=True)

    threading.Thread(target=relay, daemon=True).start()
    return process


def stop(processes):
    for process in processes.values():
        if process.poll() is None:
            if os.name == "nt":
                process.terminate()
            else:
                process.send_signal(signal.SIGINT)  # Lets the servers close their ports cleanly.
    deadline = time.monotonic() + 5
    for process in processes.values():
        try:
            process.wait(max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            process.kill()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-asr", action="store_true", help="Do not start or check Qwen speech-to-text")
    args, app_args = parser.parse_known_args()
    load_env()
    client = RemoteTranscriber(timeout=2)
    plan = plan_asr(client.url, not args.no_asr and client.available and answering(client), args.no_asr)

    processes = {}
    if plan == "local":
        python = asr_python()
        if not python.exists():
            raise SystemExit(f"{python} not found; create .venv-asr (requirements-asr.txt) or run with --no-asr")
        port = str(urlsplit(client.url).port or 80)
        print(f"Starting Qwen speech-to-text on port {port} (the model takes a while to load)", flush=True)
        processes["asr"] = start("asr", [str(python), "-m", "backend.asr_server", "--port", port])
    elif plan == "existing":
        print(f"Using the speech-to-text service already answering at {client.url}", flush=True)
    elif plan == "unreachable":
        print(f"WARNING: nothing answers at ASR_URL={client.url}; Listen will fail until the tunnel/Jetson is up", flush=True)
    else:
        print("Speech-to-text off (no ASR_URL, or --no-asr)", flush=True)
    processes["app"] = start("app", [sys.executable, "-m", "backend.app", *app_args])
    print("Ctrl+C stops everything.", flush=True)

    if os.name != "nt":
        for sig in (signal.SIGTERM, signal.SIGHUP):  # Terminal closed or launcher killed.
            signal.signal(sig, signal.default_int_handler)
    try:
        while True:
            for name, process in processes.items():
                if process.poll() is not None:
                    print(f"{name} exited with code {process.returncode}; stopping the rest", flush=True)
                    stop(processes)
                    raise SystemExit(process.returncode or 1)
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("Stopping...", flush=True)
        stop(processes)


if __name__ == "__main__":
    main()
