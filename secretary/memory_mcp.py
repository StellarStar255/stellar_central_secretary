"""Connect a local MCP client to the running Stellar Secretary service."""
import argparse
import json
import urllib.error
import urllib.request
from typing import Any


class LocalOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise ValueError('The local memory endpoint redirected unexpectedly.')


def build_server(port):
    from mcp.server.fastmcp import FastMCP

    server = FastMCP('Stellar Secretary Memory')
    base = f'http://127.0.0.1:{port}'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), LocalOnly())

    def request(path, payload=None, token=''):
        body = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(base + path, data=body, headers={
            'Content-Type': 'application/json', 'X-Knowledge-Token': token,
        })
        try:
            with opener.open(req, timeout=20) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code in (400,403):
                raise ValueError(json.load(error)['error']) from None
            if error.code == 404:
                raise ValueError('Open a Stellar Secretary build with Memory MCP support.') from None
            raise ValueError('Stellar Secretary could not complete the memory request.') from None
        except OSError:
            raise ValueError(f'Open Stellar Secretary on this computer (port {port}) and try again.') from None

    def memory(**payload):
        status = request('/api/status')
        if status.get('application') != 'stellar-central-secretary' or not status.get('token'):
            raise ValueError('The selected port does not serve Stellar Secretary.')
        return request('/api/memory', payload, status['token'])

    @server.tool(annotations={'readOnlyHint': True, 'openWorldHint': False})
    def search_memory(query: str, limit: int = 8, offset: int = 0) -> dict[str, Any]:
        """Search local archived memory. Use citations for matching excerpts, attachment names, known PDF pages and local links."""
        return memory(action='search', query=query, limit=limit, offset=offset)

    @server.tool(annotations={'readOnlyHint': True, 'openWorldHint': False})
    def read_memory(record_id: str, field: str = 'text', offset: int = 0, limit: int = 5000) -> dict[str, Any]:
        """Read archived text or its summary. Use next_offset to continue reading a long entry."""
        return memory(action='read', record_id=record_id, field=field, offset=offset, limit=limit)

    return server


async def check_connection(port):
    import asyncio
    from pathlib import Path
    import sys
    import uuid
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    args = [] if getattr(sys, 'frozen', False) else [str(Path(__file__).resolve())]
    params = StdioServerParameters(command=sys.executable, args=[*args, '--port', str(port)])
    async with asyncio.timeout(28), stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            result = await session.call_tool('search_memory', {'query': uuid.uuid4().hex, 'limit': 1})
            if result.isError:
                # Return the service error after closing the SDK task groups normally.
                return result.content[0].text if result.content else 'Memory read failed.'
    return ''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8768, help='Stellar Secretary local port')
    parser.add_argument('--check', action='store_true', help='Test read-only access to the running library')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('Port must be between 1 and 65535.')
    try:
        if args.check:
            import asyncio
            error = asyncio.run(check_connection(args.port))
            if error:
                parser.exit(1, error+'\n')
        else:
            build_server(args.port).run(transport='stdio')
    except ModuleNotFoundError as exc:
        if exc.name == 'mcp':
            parser.exit(1, 'Install the optional MCP dependency with pip install -r requirements-mcp.txt.\n')
        raise


if __name__ == '__main__':
    main()
