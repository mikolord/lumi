"""Build the prototype's metadata catalogue from the actual demo files (requires Pillow)."""
import json
import struct
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def boxes(data, start=0, end=None):
    end = len(data) if end is None else end
    while start + 8 <= end:
        size, kind = struct.unpack_from('>I4s', data, start)
        header = 8
        if size == 1:
            size = struct.unpack_from('>Q', data, start + 8)[0]
            header = 16
        if size == 0:
            size = end - start
        if size < header or start + size > end:
            break
        yield kind, start + header, start + size
        start += size


def movie_metadata(path):
    data = path.read_bytes()
    result = dict(name=path.name, format='MP4', bytes=len(data))

    def visit(start, end):
        for kind, a, b in boxes(data, start, end):
            if kind in (b'moov', b'trak', b'mdia'):
                visit(a, b)
            elif kind == b'tkhd' and b - a >= 8:
                width, height = struct.unpack_from('>II', data, b - 8)
                if width and height:
                    result.update(width=width >> 16, height=height >> 16)
            elif kind == b'mvhd':
                version = data[a]
                offset = a + (20 if version else 12)
                scale = struct.unpack_from('>I', data, offset)[0]
                duration = struct.unpack_from('>Q' if version else '>I', data, offset + 4)[0]
                if scale:
                    result['duration'] = round(duration / scale, 3)
    visit(0, len(data))
    return result


def image_metadata(path):
    with Image.open(path) as image:
        exif = image.getexif()
        details = exif.get_ifd(34665) if 34665 in exif else {}
        orientation = exif.get(274, 1)
        width, height = image.size
        if orientation in (5, 6, 7, 8):
            width, height = height, width
        result = dict(name=path.name, format=image.format, bytes=path.stat().st_size, width=width, height=height)
        for field, value in [('camera', ' '.join(str(exif.get(tag, '')).strip() for tag in (271, 272)).strip()), ('lens', details.get(42036))]:
            if value:
                result[field] = str(value)
        taken = details.get(36867)
        if taken and len(taken) >= 19:
            result['takenAt'] = taken[:10].replace(':', '-') + 'T' + taken[11:19]
        for field, tag in [('aperture', 33437), ('exposure', 33434), ('iso', 34855), ('focalLength', 37386)]:
            value = details.get(tag)
            if isinstance(value, (int, float)) or hasattr(value, 'denominator'):
                result[field] = float(value)
        gps = exif.get_ifd(34853) if 34853 in exif else {}
        if gps.get(2) and gps.get(4):
            def degrees(value):
                return float(value[0]) + float(value[1]) / 60 + float(value[2]) / 3600
            result['latitude'] = degrees(gps[2]) * (-1 if gps.get(1) == 'S' else 1)
            result['longitude'] = degrees(gps[4]) * (-1 if gps.get(3) == 'W' else 1)
        return result


if __name__ == '__main__':
    catalogue = {}
    for path in sorted((ROOT / 'assets').iterdir()):
        if path.suffix.lower() in ('.jpg', '.jpeg', '.png'):
            catalogue['assets/' + path.name] = image_metadata(path)
        elif path.suffix.lower() == '.mp4':
            catalogue['assets/' + path.name] = movie_metadata(path)
    (ROOT / 'metadata-data.js').write_text('window.PHOTO_FILE_METADATA=' + json.dumps(catalogue, ensure_ascii=False, separators=(',', ':')) + ';\n', encoding='utf-8')
    print(f'Metadata extracted from {len(catalogue)} actual media files')
