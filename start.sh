set -euo pipefail
cd "$(dirname "$0")"
URL="http://localhost:8000"

echo "Starting the Scam Detection Chat Assistant..."

if ! docker info >/dev/null 2>&1; then
  if [[ "$(uname)" == "Darwin" ]]; then
    echo "Docker is not running. Starting Docker Desktop..."
    open -a Docker
  else
    echo "Docker is not running. Start Docker, then run this again."
    exit 1
  fi
  for _ in $(seq 1 60); do
    sleep 3
    docker info >/dev/null 2>&1 && break
  done
  docker info >/dev/null 2>&1 || { echo "Docker did not start within 3 minutes."; exit 1; }
fi
echo "[1/4] Docker is running."

[[ -f .env ]] || { touch .env; echo "      No .env found - created an empty one. Add ETHERSCAN_API_KEY=... for full results."; }

echo "[2/4] Building and starting containers (first run can take a few minutes)..."
docker compose up --build -d

echo "[3/4] Checking the language model..."
for _ in $(seq 1 30); do
  docker compose exec -T ollama ollama list >/dev/null 2>&1 && break
  sleep 2
done
if ! docker compose exec -T ollama ollama list | grep -qi "llama3.1"; then
  echo "      Downloading llama3.1 - this is several GB and only happens once..."
  docker compose exec -T ollama ollama pull llama3.1
fi

echo "[4/4] Waiting for the website..."
for _ in $(seq 1 60); do
  curl -fs "$URL" >/dev/null 2>&1 && break
  sleep 2
done
curl -fs "$URL" >/dev/null 2>&1 || { echo "The website did not respond. Run: docker compose logs bot"; exit 1; }

echo
echo "=========================================================="
echo "  Assistant is ready: $URL"
echo "=========================================================="
echo
if command -v open >/dev/null 2>&1; then open "$URL"
elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"
fi
echo "To shut everything down, run: docker compose down"