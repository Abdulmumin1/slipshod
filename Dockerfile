# The slipshod web demo.   docker build -t slipshod . && docker run -p 7860:7860 slipshod
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10 \
    GRADIO_ANALYTICS_ENABLED=False \
    SLIPSHOD_WORK=/data \
    SLIPSHOD_HAND_FONT=/fonts/Kalam-Regular.ttf

# An OFL-licensed handwriting font for hand-filled forms.
RUN mkdir /fonts && python -c "import urllib.request as u; u.urlretrieve('https://github.com/google/fonts/raw/main/ofl/kalam/Kalam-Regular.ttf', '/fonts/Kalam-Regular.ttf')"

# Dependencies first, in separate layers, so code changes don't reinstall them.
RUN pip install "numpy>=1.26" "pillow>=10" "openpyxl>=3.1"
RUN pip install "pymupdf>=1.24"
RUN pip install "gradio>=5"

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-deps .

# Bake the benchmark and the baseline report into the image so cold starts are fast.
RUN python -c "from slipshod.app import ensure_benchmark, score_baseline; ensure_benchmark(); score_baseline()"

EXPOSE 7860
CMD ["python", "-c", "from slipshod.app import launch; launch(server_name='0.0.0.0')"]
