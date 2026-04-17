"""rtfm — local CLI tool for command-line help via Ollama."""

import argparse
import http.client
import json
import sys

SYSTEM_CMD = (
    "Reply with ONLY the shell command(s) that answer the question. "
    "No explanation, no preamble, no markdown, no code fences. "
    "Just the raw command(s), one per line."
)

SYSTEM_QNA = (
    "You are a helpful terminal assistant. "
    "Answer the user's question concisely and clearly. "
    "Use plain text. Do not use markdown or code fences."
)


def main():
    parser = argparse.ArgumentParser(usage="rtfm [-q] <question>")
    parser.add_argument("-q", action="store_true",
                        help="ask a general question instead of getting a command")
    parser.add_argument("query", nargs="*")
    args = parser.parse_args()

    if not args.query:
        parser.print_help()
        sys.exit(1)

    system = SYSTEM_QNA if args.q else SYSTEM_CMD

    body = json.dumps({
        "model": "qwen3.5:27b",
        "messages": [
            {"role": "system", "content": system},
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
