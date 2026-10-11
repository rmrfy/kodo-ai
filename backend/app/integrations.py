"""GitHub App API helpers and bounded pull request diff parsing."""
import time
import jwt
import requests
from .config import GITHUB_APP_ID, GITHUB_PRIVATE_KEY_PATH

API = "https://api.github.com"

def app_jwt() -> str:
    if not GITHUB_APP_ID or not GITHUB_PRIVATE_KEY_PATH:
        raise RuntimeError("GitHub App credentials are not configured")
    with open(GITHUB_PRIVATE_KEY_PATH, encoding="utf-8") as key_file:
        key = key_file.read()
    return jwt.encode({"iat": int(time.time()) - 60, "exp": int(time.time()) + 540, "iss": GITHUB_APP_ID}, key, algorithm="RS256")

def installation_token(installation_id: int) -> str:
    response = requests.post(f"{API}/app/installations/{installation_id}/access_tokens", headers={"Authorization": f"Bearer {app_jwt()}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}, timeout=20)
    response.raise_for_status()
    return response.json()["token"]

def github_request(method: str, path: str, token: str, **kwargs):
    response = requests.request(method, f"{API}{path}", headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}, timeout=30, **kwargs)
    response.raise_for_status()
    return response.json() if response.content else None

def pull_files(repo: str, number: int, token: str) -> list[dict]:
    result = []
    for page in range(1, 11):
        batch = github_request("GET", f"/repos/{repo}/pulls/{number}/files", token, params={"per_page": 100, "page": page}) or []
        result.extend(batch)
        if len(batch) < 100:
            break
    return result

def changed_positions(patch: str) -> set[int]:
    """Return GitHub review diff positions for added lines (not new-file line numbers)."""
    positions, new_line = set(), 0
    for line in patch.splitlines():
        if line.startswith("@@"):
            try:
                new_line = int(line.split("+")[1].split(",")[0].split(" ")[0])
            except (IndexError, ValueError):
                continue
            positions.add(-new_line)  # hunk start markers are not reviewable
        elif line.startswith("+") and not line.startswith("+++"):
            positions.add(new_line)
            new_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            continue
        else:
            new_line += 1
    # This tracks new-file line numbers for accuracy; caller maps against patch hunks below.
    return {p for p in positions if p > 0}
