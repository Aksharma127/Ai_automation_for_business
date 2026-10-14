# Production image for the Workflow Agent HTTP API.
#   docker build -t workflow-agent .
#   docker run -p 8000:8000 -e API_KEYS=change-me workflow-agent
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install ".[api,postgres,anthropic,openai]"

COPY config ./config
COPY data ./data
COPY evals ./evals
COPY examples ./examples

RUN useradd --create-home --uid 10001 agent \
    && chmod -R a+rX /app \
    && mkdir -p /app/runs /app/outputs \
    && chown -R agent:agent /app/runs /app/outputs
USER agent

ENV APP_ROOT=/app \
    APP_ENV=production \
    LOG_JSON=1 \
    WORKFLOW_EXCEL=/app/data/AI_Agent_Workflow_Assessment.xlsx \
    WORKFLOW_BINDINGS=/app/config/workflow_bindings.yaml \
    UPLOAD_DIR=/app/runs/uploads \
    OUTPUT_DIR=/app/outputs

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "--factory", "workflow_agent.api:create_app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--workers", "1"]
