FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

# Third-party deps first, so this layer caches across SDK rebuilds.
RUN uv pip install --system --no-cache \
    "fastapi>=0.111.0" \
    "uvicorn[standard]>=0.29.0" \
    "anthropic>=0.25.0" \
    "openai>=1.25.0" \
    "httpx>=0.27.0"

# The SDK installs from a wheel built out of the sengol tree, not from PyPI:
# `sengol` is proprietary from 2.0 and is published to no public index. `make
# wheel` puts the file here. A customer's Dockerfile installs from their own
# index instead, which is why agent/pyproject.toml still declares the range.
COPY vendor/sengol-*.whl /tmp/wheels/
RUN uv pip install --system --no-cache /tmp/wheels/sengol-*.whl \
    && rm -rf /tmp/wheels

COPY . .

EXPOSE 3000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "3000"]
