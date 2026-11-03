#!/bin/bash
set -euo pipefail
cd /path/to/llm-factory/real-web-revalidation-20261102/demo
export PYTHONPATH=src:.
export FACTORY_DOCKER_COMMAND='sudo -n docker'
export FACTORY_PRIVATE=/path/to/private-config/llm-factory-web-revalidation-20261102
export FACTORY_SECRET_DIR="$FACTORY_PRIVATE"
export COMPOSE_PROJECT_NAME=factory-web-verify-20261102
export FACTORY_NEO4J_HTTP_PORT=17475
export FACTORY_NEO4J_BOLT_PORT=17688
mkdir -p -m 700 "$FACTORY_PRIVATE"
cp -n configs/models/runtime.example.env "$FACTORY_PRIVATE/model.env"
# Existing authorized provider credentials; never print their values.
cp /path/to/private-model/model.env "$FACTORY_PRIVATE/model.env"
chmod 600 "$FACTORY_PRIVATE/model.env"
sudo -n docker inspect llm-factory-neo4j --format '{{.Id}} {{.State.StartedAt}} {{.RestartCount}}' > ../evidence/existing-neo4j-before.txt
sudo -n docker image inspect llm-factory-metrics-sandbox:latest --format '{{.Id}}' > ../evidence/sandbox-before.txt
make neo4j > ../evidence/neo4j-setup.log 2>&1
export FACTORY_KNOWLEDGE_BACKEND=neo4j
export FACTORY_METRICS_KNOWLEDGE="$FACTORY_PRIVATE/knowledge.json"
.venv/bin/python -m factory metrics-knowledge-init --knowledge "$FACTORY_METRICS_KNOWLEDGE" > ../evidence/knowledge-init.txt 2>&1
make sandbox > ../evidence/sandbox-build.log 2>&1
export FACTORY_METRICS_IMAGE="$(cat .runtime/bootstrap/image-id)"
export FACTORY_METRICS_STATE="$(pwd -P)/.runtime/poc"
export FACTORY_METRICS_MODEL_ENV="$FACTORY_PRIVATE/model.env"
export FACTORY_METRICS_CAMPAIGN="$FACTORY_PRIVATE/campaign.sqlite"
.venv/bin/python -m factory metrics-ingest \
  --state "$FACTORY_METRICS_STATE" --mode api \
  --campaign "$FACTORY_METRICS_CAMPAIGN" --env-file "$FACTORY_METRICS_MODEL_ENV" \
  --knowledge "$FACTORY_METRICS_KNOWLEDGE" --root materials/metrics \
  --output "$FACTORY_PRIVATE/knowledge-snapshot.json" > ../evidence/real-ingest.json 2> ../evidence/real-ingest.stderr
# Port override is the only Web-command deviation, to isolate the existing service.
export STREAMLIT_SERVER_PORT=18503
nohup make web PYTHON=".venv/bin/python" \
  > ../evidence/web.log 2>&1 < /dev/null &
echo $! > ../evidence/web-launcher.pid
