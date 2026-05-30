#!/usr/bin/env python3
"""No-dependency smoke test for a local Ollama service."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def request_json(url: str, payload: dict | None = None, timeout: int = 120) -> dict:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test Ollama for Asynchronous.")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="qwen3:14b")
    parser.add_argument("--prompt", default="Write one vivid sentence about local-first podcast production.")
    parser.add_argument(
        "--think",
        action="store_true",
        help="Allow models that support Ollama thinking mode to emit reasoning.",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    try:
        tags = request_json(f"{base_url}/api/tags", timeout=5)
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        print(f"Ollama API is not reachable at {base_url}: {exc}", file=sys.stderr)
        return 2

    models = [
        str(model.get("name", ""))
        for model in tags.get("models", [])
        if isinstance(model, dict)
    ]
    print(f"Ollama API reachable: {base_url}")
    print("Installed models: " + (", ".join(models) if models else "(none)"))
    if args.model not in models:
        print(f"Model {args.model!r} is not installed yet. Run: ollama pull {args.model}")
        return 1

    payload = {
        "model": args.model,
        "stream": False,
        "think": bool(args.think),
        "messages": [
            {
                "role": "system",
                "content": "You are a concise writing model for a podcast pipeline.",
            },
            {"role": "user", "content": args.prompt},
        ],
        "options": {"num_predict": 256, "temperature": 0.4},
    }
    try:
        result = request_json(f"{base_url}/api/chat", payload=payload, timeout=180)
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        print(f"Ollama chat request failed: {exc}", file=sys.stderr)
        return 3

    message = result.get("message", {})
    text = str(message.get("content", "")).strip()
    if not text:
        if message.get("thinking"):
            print(
                "Ollama returned thinking tokens but no message content. "
                "Retry without --think or increase num_predict.",
                file=sys.stderr,
            )
        else:
            print("Ollama returned no message content.", file=sys.stderr)
        return 4
    print("\nSample response:")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
