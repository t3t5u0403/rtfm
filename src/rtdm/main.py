"""rtdm CLI entry point.

Phase 7b transitional shim: this is the original single-file rtfm CLI,
relocated to ``src/rtdm/main.py`` so the package layout matches what
``pipx`` expects.  Subsequent commits in Phase 7b split this file into
``config``, ``backends.local``, ``backends.remote``, and a thin
dispatcher.  Until then it talks to local Ollama exactly as before.
"""

import argparse
import http.client
import json
import shutil
import subprocess
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

SYSTEM_EXPLAIN = (
    "Explain the given shell command in plain English. "
    "Break down each part (flags, arguments, pipes, redirects, etc.) concisely. "
    "Use plain text. Do not use markdown or code fences."
)


def copy_to_clipboard(text):
    """Copy text to system clipboard."""
    if shutil.which("wl-copy"):
        cmd = ["wl-copy"]
    elif shutil.which("xclip"):
        cmd = ["xclip", "-selection", "clipboard"]
    elif shutil.which("xsel"):
        cmd = ["xsel", "--clipboard", "--input"]
    else:
        print("No clipboard tool found (install wl-copy, xclip, or xsel)",
              file=sys.stderr)
        return False
    subprocess.run(cmd, input=text.encode(), check=True)
    return True


def stream_response(resp):
    """Stream tokens from Ollama, print live, and return full output."""
    chunks = []
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
            chunks.append(tok)
    print()
    return "".join(chunks)


def main():
    parser = argparse.ArgumentParser(usage="rtfm [-q | -e] [-c] [-x] <question>")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("-q", action="store_true",
                      help="ask a general question instead of getting a command")
    mode.add_argument("-e", action="store_true",
                      help="explain a command")
    parser.add_argument("-c", action="store_true",
                        help="copy the output to clipboard")
    parser.add_argument("-x", action="store_true",
                        help="execute the returned command (with confirmation)")
    parser.add_argument("query", nargs="*")
    args = parser.parse_args()

    if not args.query:
        parser.print_help()
        sys.exit(1)

    if args.x and (args.q or args.e):
        print("Error: -x can only be used in command mode (not with -q or -e)",
              file=sys.stderr)
        sys.exit(1)

    if args.e:
        system = SYSTEM_EXPLAIN
    elif args.q:
        system = SYSTEM_QNA
    else:
        system = SYSTEM_CMD

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
        output = stream_response(resp)
        conn.close()
    except (ConnectionRefusedError, OSError):
        print("Could not connect to Ollama. Is it running? (`ollama serve`)",
              file=sys.stderr)
        sys.exit(1)

    if args.c:
        if copy_to_clipboard(output):
            print("(copied to clipboard)", file=sys.stderr)

    if args.x:
        try:
            answer = input("Run? [y/N] ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(0)
        if answer == "y":
            subprocess.run(output, shell=True)


if __name__ == "__main__":
    main()
