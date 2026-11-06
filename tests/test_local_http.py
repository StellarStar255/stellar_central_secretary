import unittest
from http.server import BaseHTTPRequestHandler
from unittest.mock import patch
from secretary.local_http import LocalHTTPServer


class LocalHTTPTest(unittest.TestCase):
    def test_numeric_loopback_server_starts_without_reverse_dns(self):
        with patch('socket.getfqdn',side_effect=AssertionError('No reverse DNS for a numeric loopback service')):
            server=LocalHTTPServer(('127.0.0.1',0),BaseHTTPRequestHandler)
            try:
                self.assertEqual(server.server_name,'127.0.0.1')
                self.assertGreater(server.server_port,0)
                self.assertEqual(server.socket.getsockname(),('127.0.0.1',server.server_port))
            finally:server.server_close()
