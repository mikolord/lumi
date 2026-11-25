FROM python:3.12-slim
ENV OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir opencv-python-headless==4.11.0.86 numpy==2.2.6
COPY download_models.py /download_models.py
RUN python /download_models.py
COPY service.py /service.py
COPY metrics.py /metrics.py
USER 65534:65534
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health',timeout=2)"
CMD ["python","/service.py"]
