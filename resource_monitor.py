"""Aggregate gallery + private inference consumption, for administrators only."""
import json
import os
import urllib.request
from faces.metrics import Monitor

monitor=Monitor()


def snapshot():
    gallery=monitor.sample();worker=None
    if os.environ.get('PHOTO_FACE_URL') and os.environ.get('PHOTO_FACE_TOKEN'):
        try:
            request=urllib.request.Request(os.environ['PHOTO_FACE_URL'].rstrip('/')+'/metrics',headers={'Authorization':'Bearer '+os.environ['PHOTO_FACE_TOKEN']})
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self,*args,**kwargs):return None
            with urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect).open(request,timeout=2) as response:worker=json.loads(response.read(16384))
        except Exception:pass
    components=[dict(name='Медиатека',**gallery)]
    if worker:components.append(dict(name='Распознавание людей',**worker))
    cpu=sum(c['cpu'] for c in components if c.get('cpu') is not None) if all(c.get('cpu') is not None for c in components) else None
    memory=sum(c['memory'] for c in components if c.get('memory') is not None) if any(c.get('memory') is not None for c in components) else None
    return dict(cpu=cpu/gallery['cores'] if cpu is not None else None,memory=memory,cores=gallery['cores'],components=components,partial=bool(os.environ.get('PHOTO_FACE_URL') and worker is None))
