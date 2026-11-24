import asyncio
import importlib.util
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from secretary.core import Archive
from secretary.local_http import LocalHTTPServer
from secretary.memory_access import read_memory
from secretary import memory_setup
from secretary.server import Service, handler


class MemoryAccessTest(unittest.TestCase):
    def test_desktop_opt_in_survives_restart_and_can_be_revoked(self):
        with tempfile.TemporaryDirectory() as folder:
            service = Service(folder)
            try:
                self.assertFalse(service.memory_mcp)
                memory_setup.configure(service, True)
            finally:
                service.close()
            service = Service(folder)
            try:
                self.assertTrue(service.memory_mcp)
                service.archive.set_company_mode(True)
                with self.assertRaisesRegex(ValueError, 'Company Mode'):
                    memory_setup.configure(service, True)
                memory_setup.configure(service, False)
            finally:
                service.close()
            service = Service(folder)
            try:
                self.assertFalse(service.memory_mcp)
            finally:
                service.close()

    def test_search_and_paged_read(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Archive(folder)
            record, _ = archive.add('Rain garden', 'Concrete fixture body', url='https://example.com/record')
            archive.add('Unrelated', 'Different material')
            result = read_memory(archive, {'action': 'search', 'query': 'Rain garden'})
            self.assertEqual([item['id'] for item in result['items']], [record])
            result = read_memory(archive, {'action': 'read', 'record_id': record, 'limit': 8})
            self.assertEqual(result['content'], 'Concrete')
            self.assertEqual(result['next_offset'], 8)
            self.assertEqual(result['url'], 'https://example.com/record')
            following = read_memory(archive, {'action': 'read', 'record_id': record, 'offset': 8})
            self.assertEqual(following['content'], ' fixture body')
            self.assertIsNone(following['next_offset'])
            archive.set_company_mode(True)
            with self.assertRaisesRegex(ValueError, 'Company Mode'):
                read_memory(archive, {'action': 'read', 'record_id': record})

    @unittest.skipUnless(importlib.util.find_spec('mcp'), 'Install requirements-mcp.txt for the stdio test')
    def test_real_stdio_tools_require_opt_in_and_obey_company_mode(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        with tempfile.TemporaryDirectory() as folder:
            service = Service(folder)
            record, _ = service.archive.add('日报例会', '用于检索的本机资料')
            with LocalHTTPServer(('127.0.0.1', 0), handler(service)) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                params = StdioServerParameters(
                    command=sys.executable,
                    args=[str(Path(__file__).resolve().parents[1]/'secretary/memory_mcp.py'),
                          '--port', str(server.server_port)])

                async def exercise():
                    async with stdio_client(params) as (read_stream, write_stream):
                        async with ClientSession(read_stream, write_stream) as session:
                            await session.initialize()
                            self.assertEqual({tool.name for tool in (await session.list_tools()).tools},
                                             {'search_memory', 'read_memory'})
                            result = await session.call_tool('search_memory', {'query': '日报'})
                            self.assertTrue(result.isError)
                            self.assertIn('--memory-mcp', result.content[0].text)
                            service.memory_mcp = True
                            result = await session.call_tool('search_memory', {'query': '日报'})
                            self.assertFalse(result.isError, result)
                            self.assertEqual(result.structuredContent['items'][0]['id'], record)
                            result = await session.call_tool('read_memory', {'record_id': record})
                            self.assertFalse(result.isError, result)
                            self.assertEqual(result.structuredContent['content'], '用于检索的本机资料')
                            service.archive.set_company_mode(True)
                            result = await session.call_tool('read_memory', {'record_id': record})
                            self.assertTrue(result.isError)
                            self.assertIn('Company Mode', result.content[0].text)

                try:
                    asyncio.run(exercise())
                finally:
                    server.shutdown()
                    thread.join(timeout=3)
                    service.close()
