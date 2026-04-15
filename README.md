# rtfm

Local CLI tool for command-line help via [Ollama](https://ollama.com). Ask a question in plain English, get just the command back. No paid APIs, no internet required.

Inspired by [how2](https://github.com/santinic/how2).

## Demo

```
$ rtfm merge all pdfs into one using pdfunite
pdfunite *.pdf merged.pdf

$ rtfm update packages using pacman
sudo pacman -Syu

$ rtfm convert jpeg to png
convert image.jpg image.png

$ rtfm list downloads with newest files at the bottom
ls -ltr ~/Downloads
```

## Install

Requires [Ollama](https://ollama.com) running locally with a model pulled (default: `qwen3.5:27b`).

```bash
# with pipx (recommended)
pipx install -e .

# or with pip in a venv
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

## Usage

```
rtfm <your question in plain english>
```

## Configuration

Edit `rtfm.py` directly to change:

- **Model** — change `qwen3.5:27b` to any model you have in Ollama
- **Host** — change `localhost` to a remote IP for use over LAN or Tailscale

## How it works

Single Python file, zero dependencies. Sends your question to the Ollama API with a system prompt that enforces command-only responses. Streams tokens to stdout in real-time.
