"""rtfm — local CLI tool for command-line help via Ollama."""

import argparse
import http.client
import json
import sys

SYSTEM = (
    "Reply with ONLY the shell command(s) that answer the question. "
    "No explanation, no preamble, no markdown, no code fences. "
    "Just the raw command(s), one per line."
)


def main():
    parser = argparse.ArgumentParser(usage="rtfm <question>")
    parser.add_argument("query", nargs="*")
    args = parser.parse_args()

    if not args.query:
        parser.print_help()
        sys.exit(1)

    body = json.dumps({
        "model": "qwen3.5:27b",
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": " ".join(args.query)},
        ],
        "stream": True,
        "think": False,
        "options": {"num_ctx": 2048},
    }).encode()

    try:
        conn = http.client.HTTPConnection("localhost", 11434)
        conn.request("POST", "/api/chat", body=body,
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()

        while True:
            line = resp.readline()
            if not line:
                break
            chunk = json.loads(line)
            if chunk.get("done"):
                break
            tok = chunk.get("message", {}).get("content", "")
            if tok:
                print(tok, end="", flush=True)
        print()
        conn.close()
    except (ConnectionRefusedError, OSError):
        print("Could not connect to Ollama. Is it running? (`ollama serve`)",
              file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
