"""Serve only the TV update manifest and APK on the local network."""
import http.server
import socketserver
import re
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
PORT = 8099
class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(ROOT),**kwargs)
    def allowed(self):
        path = urlsplit(self.path).path
        return path in ('/tv/version.json', '/tv/rc-foto.apk') or re.fullmatch(r'/tv/lumi-[0-9]+-[0-9a-f]{64}\.apk', path) is not None
    def do_GET(self):
        if not self.allowed():self.send_error(404);return
        super().do_GET()
    def do_HEAD(self):
        if not self.allowed():self.send_error(404);return
        super().do_HEAD()
    def end_headers(self):
        self.send_header('Cache-Control','no-store');super().end_headers()
class Server(socketserver.ThreadingTCPServer):allow_reuse_address=True
if __name__=='__main__':
    with Server(('0.0.0.0',PORT),Handler) as server:
        print(f'Lumi TV update feed: port {PORT}',flush=True)
        server.serve_forever()
