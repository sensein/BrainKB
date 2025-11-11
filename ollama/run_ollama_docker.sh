#!/bin/bash
set -euo pipefail
NAME="ollama"
PORT="11434"
VOL="ollama"
MODEL="nomic-embed-text"

sudo docker rm -f "$NAME" >/dev/null 2>&1 || true
echo "Starting container..."
if ! sudo docker run -d --name "$NAME" -p "$PORT":11434 -v "$VOL":/root/.ollama -e OLLAMA_HOST=0.0.0.0 ollama/ollama:latest >/dev/null; then
  echo "docker run failed"; exit 1
fi

echo "Waiting for API..."
for i in {1..60}; do
  if sudo docker exec "$NAME" ollama list >/dev/null 2>&1; then ok=1; break; fi
  if ! sudo docker ps --format '{{.Names}}' | grep -qx "$NAME"; then
    echo "Container exited. Details:"; sudo docker inspect -f 'ExitCode={{.State.ExitCode}}  Error={{.State.Error}}' "$NAME"; sudo docker logs "$NAME" || true; exit 1
  fi
  sleep 1
done
[[ "${ok:-}" == "1" ]] || { echo "Timeout waiting for API"; sudo docker logs "$NAME" || true; exit 1; }

# Pull model if missing
if ! sudo docker exec "$NAME" ollama list | awk 'NR>1 {print $1}' | grep -q "^${MODEL}:"; then
  echo "Pulling model: $MODEL"; sudo docker exec -it "$NAME" ollama pull "$MODEL"
fi

echo "Ready. Test:"
echo "curl http://localhost:$PORT/api/embeddings -d '{\"model\":\"$MODEL\",\"prompt\":\"Hello\"}'"
