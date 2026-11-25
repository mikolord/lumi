"""Private CPU-only YuNet/SFace inference service. No media storage or public port."""
from http.server import BaseHTTPRequestHandler,HTTPServer
import hmac
import json
import os
import cv2
import numpy as np
from metrics import Monitor

monitor=Monitor();monitor.sample()

cv2.setNumThreads(1)
detector=cv2.FaceDetectorYN.create('/models/yunet.onnx','',(320,320),.9,.3,5000)
recognizer=cv2.FaceRecognizerSF.create('/models/sface.onnx','')
token=os.environ['PHOTO_FACE_TOKEN']
if len(token)<32:raise RuntimeError('Face service requires a strong token')


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass

    def do_GET(self):
        if self.path=='/metrics':
            if not hmac.compare_digest(self.headers.get('Authorization','').encode(),('Bearer '+token).encode()):self.send_error(401);return
            data=json.dumps(monitor.sample()).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data);return
        # Readiness contains no user data.
        if self.path!='/health':self.send_error(404);return
        data=b'{"ready":true}';self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)

    def do_POST(self):
        if not hmac.compare_digest(self.headers.get('Authorization','').encode(),('Bearer '+token).encode()):self.send_error(401);return
        if self.path!='/detect':self.send_error(404);return
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=8*1024**2:raise ValueError()
            image=cv2.imdecode(np.frombuffer(self.rfile.read(size),np.uint8),cv2.IMREAD_COLOR)
            if image is None:raise ValueError()
            h,w=image.shape[:2]
            if w*h>25_000_000:raise ValueError()
            scale=min(1.,1280/max(h,w))
            if scale<1:image=cv2.resize(image,(round(w*scale),round(h*scale)))
            h,w=image.shape[:2];detector.setInputSize((w,h));_,found=detector.detect(image)
            faces=[]
            if found is not None:
                for face in found[:100]:
                    if min(face[2:4])<24:continue
                    aligned=recognizer.alignCrop(image,face)
                    vector=recognizer.feature(aligned).flatten();norm=float(np.linalg.norm(vector))
                    if norm<=0:continue
                    x,y,bw,bh=[float(v) for v in face[:4]];left=max(0.,x);top=max(0.,y);right=min(float(w),x+bw);bottom=min(float(h),y+bh)
                    if right<=left or bottom<=top:continue
                    faces.append(dict(box=[left/w,top/h,(right-left)/w,(bottom-top)/h],vector=(vector/norm).tolist()))
            data=json.dumps(dict(faces=faces)).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
        except Exception:self.send_error(422,'Unable to process image')


HTTPServer(('0.0.0.0',8001),Handler).serve_forever()
