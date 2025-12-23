from fastapi import FastAPI, Request

app = FastAPI()

@app.post("/github-webhook")
async def github_webhook(request: Request):
    payload = await request.json()

    # Check if this is a PR opened event
    if payload.get("action") == "opened" and "pull_request" in payload:
        pass

    return {"success": True, "message": "hello from kodo :)"}