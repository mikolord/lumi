import functools
import importlib.util
import json
import threading
import sys
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('photo_server', ROOT / 'server.py')
server_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server_module)


class StorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(server_module.Handler, directory=str(ROOT)))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_actual_storage_and_no_cache(self):
        with urllib.request.urlopen(self.base + '/api/storage?fresh=1') as response:
            data = json.load(response)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertGreater(data['total'], 0)
        self.assertGreaterEqual(data['free'], 0)
        self.assertLessEqual(data['used'], data['total'])
        self.assertEqual(data['scope'], 'volume')
        media = list((ROOT / 'assets').glob('[0-9]*.jpg')) + list((ROOT / 'assets').glob('*.mp4'))
        self.assertEqual(data['media_bytes'], sum(path.stat().st_size for path in media))
        with urllib.request.urlopen(urllib.request.Request(self.base + '/api/storage', method='HEAD')) as response:
            self.assertEqual(response.read(), b'')

    def test_entry_points_are_revalidated(self):
        for path in ('/','/index.html','/boot.js','/sw.js','/VERSION'):
            with urllib.request.urlopen(self.base+path) as response:self.assertEqual(response.headers['Cache-Control'],'no-cache, must-revalidate')

    def test_video_ranges_still_work(self):
        for filename in ('demo-video.mp4', 'demo-vertical.mp4'):
            request = urllib.request.Request(self.base + '/assets/' + filename, headers={'Range': 'bytes=10-25'})
            with urllib.request.urlopen(request) as response:
                self.assertEqual(response.status, 206)
                self.assertEqual(response.read(), (ROOT / 'assets' / filename).read_bytes()[10:26])


if __name__ == '__main__':
    unittest.main()
