FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

# Install dependencies first for better layer caching
RUN uv pip install --system --no-cache \
    "fastapi>=0.111.0" \
    "uvicorn[standard]>=0.29.0" \
    "sengol>=2.0,<3" \
    "anthropic>=0.25.0" \
    "openai>=1.25.0" \
    "httpx>=0.27.0"

COPY . .

EXPOSE 3000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "3000"]
