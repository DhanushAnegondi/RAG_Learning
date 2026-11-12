FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# Dependencies first: this layer is cached until requirements.txt changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml ./
COPY src ./src
COPY data ./data
# Editable install keeps config.py's project-relative defaults (data/, chroma_store/) valid.
RUN pip install --no-cache-dir --no-deps -e .

RUN useradd --create-home app && chown -R app:app /app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"
CMD ["crag", "serve", "--host", "0.0.0.0"]
