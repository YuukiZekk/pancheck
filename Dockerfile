FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    SIEVE_DATA=/data \
    TZ=Asia/Shanghai

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY sieve.py app.py ./
COPY panel ./panel
COPY static ./static
COPY tools ./tools
# 版本号（CI 传入提交号；页面上显示，方便对版）。放在最后，不影响前面各层的构建缓存
ARG PANCHECK_VERSION=dev
ENV PANCHECK_VERSION=$PANCHECK_VERSION

EXPOSE 8760
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8760/healthz')" || exit 1
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8760"]
