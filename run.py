import os
import uvicorn

PORT = int(os.environ.get("PORT", "8000"))

if __name__ == "__main__":
    print(f"\n  Assistant is ready: http://localhost:{PORT}\n", flush=True)
    uvicorn.run("server:app", host="0.0.0.0", port=PORT)