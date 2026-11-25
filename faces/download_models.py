"""Download pinned OpenCV models and verify upstream Git LFS SHA256."""
import hashlib
from pathlib import Path
import urllib.request

COMMIT='48b10fa505aeb51fbd127fc60a5c660040e823b7'
root=Path('/models');root.mkdir(exist_ok=True)
for folder,name,target,digest in [
    ('face_detection_yunet','face_detection_yunet_2023mar.onnx','yunet.onnx','8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4'),
    ('face_recognition_sface','face_recognition_sface_2021dec.onnx','sface.onnx','0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79')]:
    url=f'https://media.githubusercontent.com/media/opencv/opencv_zoo/{COMMIT}/models/{folder}/{name}'
    with urllib.request.urlopen(url,timeout=120) as response:data=response.read(50*1024**2)
    if hashlib.sha256(data).hexdigest()!=digest:raise RuntimeError('Model checksum mismatch')
    (root/target).write_bytes(data)
    with urllib.request.urlopen(f'https://raw.githubusercontent.com/opencv/opencv_zoo/{COMMIT}/models/{folder}/LICENSE',timeout=30) as response:(root/(target+'.LICENSE')).write_bytes(response.read())
