#!/usr/bin/env python3
"""email_trigger.py — Flask webhook to trigger Dialog podcast generation.

Dispatch strategy (in priority order):
  1. GitHub Actions repository_dispatch  — if GH_TOKEN + GITHUB_USER + GITHUB_REPO are set
  2. Local subprocess fallback           — for local development without GitHub credentials
"""

import hmac
import hashlib
import json
import logging
import os
import subprocess
from pathlib import Path

import requests
from flask import Flask, request, jsonify

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

WEBHOOK_SECRET: str = os.environ.get("WEBHOOK_SECRET", "change-me-please")

# Guard against the empty-string-splits-to-{''} footgun
ALLOWED_SENDERS: set = {
    s.strip().lower()
    for s in os.environ.get("ALLOWED_SENDERS", "").split(",")
    if s.strip()
}

_GITHUB_API = "https://api.github.com"


# ── Auth helpers ───────────────────────────────────────────────────────────────

def _verify_secret(req) -> bool:
    try:
        sig = req.headers.get("X-Signature", "")
        if not sig:
            return False
        expected = hmac.new(
            WEBHOOK_SECRET.encode(), req.data, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


def _github_headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ.get('GH_TOKEN', '')}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    }


def _github_configured() -> bool:
    return all(
        os.environ.get(k)
        for k in ("GH_TOKEN", "GITHUB_USER", "GITHUB_REPO")
    )


# ── Dispatch strategies ────────────────────────────────────────────────────────

def _dispatch_github(topic: str) -> dict:
    """Fire a repository_dispatch event that triggers the GitHub Actions workflow."""
    user = os.environ["GITHUB_USER"]
    repo = os.environ["GITHUB_REPO"]
    url = f"{_GITHUB_API}/repos/{user}/{repo}/dispatches"

    resp = requests.post(
        url,
        headers=_github_headers(),
        json={"event_type": "podcast_request", "client_payload": {"topic": topic}},
        timeout=15,
    )
    resp.raise_for_status()  # 204 No Content on success

    actions_url = f"https://github.com/{user}/{repo}/actions"
    logger.info(f"GitHub Actions dispatched for topic: {topic!r}  →  {actions_url}")
    return {
        "method": "github_actions",
        "topic": topic,
        "actions_url": actions_url,
        "note": (
            "Generation running in GitHub Actions. "
            "Poll /webhook/status/latest for run status, "
            "or check the actions_url directly."
        ),
    }


def _spawn_local(topic: str) -> dict:
    """Fallback: spawn generate_podcast.py as a local subprocess."""
    repo_path = os.environ.get("PODCAST_REPO_PATH", ".")
    log_dir = Path(repo_path) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "latest.log"

    logger.info(f"Spawning local generation for topic: {topic!r}")
    with open(log_file, "w", encoding="utf-8") as log_fh:
        proc = subprocess.Popen(
            ["python", "generate_podcast.py", topic, "--repo", repo_path],
            stdout=log_fh,
            stderr=log_fh,
            cwd=Path(__file__).parent,
            env=os.environ.copy(),
        )
    return {
        "method": "local_subprocess",
        "pid": proc.pid,
        "topic": topic,
        "log": str(log_file),
    }


def trigger_generation(topic: str) -> dict:
    """Dispatch episode generation, preferring GitHub Actions over local subprocess."""
    if _github_configured():
        return _dispatch_github(topic)
    return _spawn_local(topic)


# ── Email helpers ──────────────────────────────────────────────────────────────

def extract_topic_from_email(subject: str, body: str) -> str:
    prefix = "PODCAST:"
    if subject.upper().startswith(prefix):
        return subject[len(prefix):].strip()
    for line in body.splitlines():
        line = line.strip()
        if line:
            return line
    return subject.strip()


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "github_configured": _github_configured(),
    })


@app.route("/webhook/email", methods=["POST"])
def inbound_email():
    sender = request.form.get("from", "")
    subject = request.form.get("subject", "")
    body = request.form.get("text", "") or request.form.get("html", "")

    if ALLOWED_SENDERS and sender:
        sender_addr = sender.split("<")[-1].rstrip(">").strip().lower()
        if sender_addr not in ALLOWED_SENDERS:
            logger.warning(f"Rejected sender: {sender_addr!r}")
            return jsonify({"error": "sender not allowed"}), 403

    topic = extract_topic_from_email(subject, body)
    if not topic:
        return jsonify({"error": "could not extract topic"}), 400

    try:
        result = trigger_generation(topic)
    except requests.HTTPError as exc:
        logger.error(f"GitHub dispatch failed: {exc}")
        return jsonify({"error": "GitHub dispatch failed", "detail": str(exc)}), 502

    logger.info(f"Generation triggered: {result}")
    return jsonify({"status": "generating", **result}), 202


@app.route("/webhook/prompt", methods=["POST"])
def direct_prompt():
    data = request.get_json(silent=True) or {}
    if data.get("secret") != WEBHOOK_SECRET and not _verify_secret(request):
        return jsonify({"error": "unauthorized"}), 401

    topic = data.get("topic", "").strip()
    if not topic:
        return jsonify({"error": "topic required"}), 400

    try:
        result = trigger_generation(topic)
    except requests.HTTPError as exc:
        logger.error(f"GitHub dispatch failed: {exc}")
        return jsonify({"error": "GitHub dispatch failed", "detail": str(exc)}), 502

    logger.info(f"Generation triggered: {result}")
    return jsonify({"status": "generating", **result}), 202


@app.route("/webhook/status/<run_id>", methods=["GET"])
def run_status(run_id: str):
    """Proxy a GitHub Actions run status. run_id can be a numeric ID or 'latest'."""
    if not _github_configured():
        return jsonify({"error": "GitHub not configured — using local subprocess mode"}), 503

    user = os.environ["GITHUB_USER"]
    repo = os.environ["GITHUB_REPO"]

    try:
        if run_id == "latest":
            # Return the most recent repository_dispatch run
            url = (
                f"{_GITHUB_API}/repos/{user}/{repo}/actions/runs"
                f"?event=repository_dispatch&per_page=1"
            )
            resp = requests.get(url, headers=_github_headers(), timeout=10)
            resp.raise_for_status()
            runs = resp.json().get("workflow_runs", [])
            if not runs:
                return jsonify({"status": "no_runs", "message": "No runs found yet"}), 404
            run = runs[0]
        else:
            url = f"{_GITHUB_API}/repos/{user}/{repo}/actions/runs/{run_id}"
            resp = requests.get(url, headers=_github_headers(), timeout=10)
            resp.raise_for_status()
            run = resp.json()

        return jsonify({
            "run_id":     run.get("id"),
            "status":     run.get("status"),
            "conclusion": run.get("conclusion"),
            "created_at": run.get("created_at"),
            "updated_at": run.get("updated_at"),
            "html_url":   run.get("html_url"),
        })

    except requests.HTTPError as exc:
        return jsonify({"error": str(exc)}), exc.response.status_code if exc.response else 502


@app.route("/status", methods=["GET"])
def status():
    """Last 40 lines of the local generation log (local mode only)."""
    repo_path = os.environ.get("PODCAST_REPO_PATH", ".")
    log_file = Path(repo_path) / "logs" / "latest.log"
    if not log_file.exists():
        return jsonify({"log": "No log yet."})
    lines = log_file.read_text(encoding="utf-8").splitlines()
    return jsonify({"log": "\n".join(lines[-40:])})


@app.route("/logs", methods=["GET"])
def logs():
    """Last 100 lines of the local generation log (local mode only)."""
    repo_path = os.environ.get("PODCAST_REPO_PATH", ".")
    log_file = Path(repo_path) / "logs" / "latest.log"
    if not log_file.exists():
        return jsonify({"log": "No log yet.", "lines": 0})
    all_lines = log_file.read_text(encoding="utf-8").splitlines()
    tail = all_lines[-100:]
    return jsonify({"log": "\n".join(tail), "lines": len(all_lines)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=False)
