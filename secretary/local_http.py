"""Numeric loopback HTTP servers do not need a reverse-DNS lookup at startup."""
from http.server import ThreadingHTTPServer
from socketserver import TCPServer


class LocalHTTPServer(ThreadingHTTPServer):
    def server_bind(self):
        TCPServer.server_bind(self)
        self.server_name=self.server_address[0]
        self.server_port=self.server_address[1]
