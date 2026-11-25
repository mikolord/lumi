FROM python:3.12-alpine
RUN apk add --no-cache ffmpeg git openssh-client
COPY requirements.txt /tmp/photo-requirements.txt
RUN pip install --no-cache-dir -r /tmp/photo-requirements.txt
WORKDIR /site
COPY index.html *.js style.css manifest.webmanifest server.py vault.py accounts.py users.py immich_import.py editor.py people.py resource_monitor.py updates.py launcher.py VERSION RUNTIME requirements.txt /site/
COPY faces/metrics.py /site/faces/metrics.py
COPY assets /site/assets
COPY icons /site/icons
CMD ["python", "launcher.py"]
