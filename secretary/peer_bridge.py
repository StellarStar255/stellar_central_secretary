"""Optional Apple nearby-device carrier for the pinned mobile TLS gateway."""
import subprocess
import sys
from pathlib import Path


def start(server_id, port):
    if sys.platform != 'darwin':
        return None
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
    binary = root / ('native/stellar-peer-bridge' if getattr(sys, 'frozen', False) else 'build/native/stellar-peer-bridge')
    if not binary.is_file():
        return None
    # No credentials or library paths cross this process boundary.
    try:
        return subprocess.Popen([str(binary), server_id, str(port)], stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return None


def stop(process):
    if process is None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
