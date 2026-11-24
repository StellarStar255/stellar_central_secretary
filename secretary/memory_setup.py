"""Desktop settings for the local, read-only MCP bridge."""
import json
from pathlib import Path
import subprocess
import sys


def command(port):
    if getattr(sys, 'frozen', False):
        filename = 'stellar-memory.exe' if sys.platform == 'win32' else 'stellar-memory'
        executable = Path(sys.executable).with_name(filename)
        return [str(executable), '--port', str(port)]
    return [sys.executable, str(Path(__file__).with_name('memory_mcp.py')), '--port', str(port)]


def configure(service, enabled):
    if type(enabled) is not bool:
        raise ValueError('Invalid memory access preference.')
    with service.archive.lock:
        if enabled and service.archive.settings()['company_mode']:
            raise ValueError('Memory MCP is unavailable while Company Mode is on.')
        marker = service.archive.root/'memory-mcp-enabled'
        if enabled:
            marker.touch()
        else:
            marker.unlink(missing_ok=True)
        service.memory_mcp = enabled


def test_connection(port):
    result = subprocess.run([*command(port), '--check'], capture_output=True, timeout=35,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        detail = result.stderr.decode('utf-8', errors='replace').strip().splitlines()
        raise ValueError(detail[-1][:400] if detail else 'Memory connection failed.')
    return {'ok': True}


def client_config(port, client):
    executable, *args = command(port)
    if client == 'codex':
        # JSON basic strings and string arrays also form valid TOML here.
        return '[mcp_servers.stellar-memory]\ncommand = '+json.dumps(executable,ensure_ascii=False)+'\nargs = '+json.dumps(args,ensure_ascii=False)
    if client not in ('gemini','claude'):
        raise ValueError('Unknown MCP client.')
    return json.dumps({'mcpServers':{'stellar-memory':{'command':executable,'args':args}}},
                      indent=2,ensure_ascii=False)
