"""Build the macOS nearby carrier with the same source used by the iPhone."""
import platform
import subprocess
from pathlib import Path


def build(root):
    root = Path(root)
    output = root / 'build/native/stellar-peer-bridge'
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['xcrun', 'swiftc', '-O', '-target', platform.machine() + '-apple-macos12.0',
                    str(root / 'ios/StellarSecretary/PairingCode.swift'),
                    str(root / 'ios/StellarSecretary/PairingNetwork.swift'),
                    str(root / 'ios/StellarSecretary/WiFiRelay.swift'),
                    str(root / 'ios/StellarSecretary/BluetoothRelay.swift'),
                    str(root / 'packaging/native/PeerBridgeMain.swift'),
                    '-Xlinker', '-sectcreate', '-Xlinker', '__TEXT', '-Xlinker', '__info_plist',
                    '-Xlinker', str(root / 'packaging/native/PeerBridge-Info.plist'),
                    '-o', str(output)], check=True)
    return output


if __name__ == '__main__':
    build(Path(__file__).resolve().parents[1])
