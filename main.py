import os
import jwt
import time
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Request

load_dotenv()
app = FastAPI()


GITHUB_APP_ID = os.getenv("GITHUB_APP_ID")
GITHUB_PRIVATE_KEY_PATH = os.getenv("GITHUB_PRIVATE_KEY_PATH")


def generate_jwt():
    with open(GITHUB_PRIVATE_KEY_PATH, "r") as f:
        private_key = f.read()
    
    payload = {
        "iat": int(time.time()) - 60,
        "exp": int(time.time()) + 600,
        "iss": GITHUB_APP_ID
    }

    token = jwt.encode(payload, private_key, algorithm="RS256")
    return token


def get_installation_token(installation_id: int):
    jwt_token = generate_jwt()

    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Accept": "application/vnd.github+json"
    }

    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    response = requests.post(url=url, headers=headers)
    response.raise_for_status()

    return response.json()["token"]


def comment_on_pr(token, repo_full_name, pr_number, body):
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json"
    }

    url = f"https://api.github.com/repos/{repo_full_name}/issues/{pr_number}/comments"
    data = {"body": body}

    response = requests.post(url=url, headers=headers, json=data)
    response.raise_for_status()


@app.post("/github-webhook")
async def github_webhook(request: Request):
    payload = await request.json()

    action = payload.get("action")
    pr = payload.get("pull_request")

    if action in ["opened", "reopened"] and pr:
        print("PR detected........")
        repo = payload["repository"]["full_name"]
        pr_number = pr["number"]
        installation_id = payload["installation"]["id"]

        token = get_installation_token(installation_id)

        body = (
            "**Kodo here!**\n\n"
            "Pull reuest detected, getting ready to share analysis...\n\n"
            "_(PR summary coming soon)_"
        )

        comment_on_pr(token, repo, pr_number, body)

    return {"success": True}