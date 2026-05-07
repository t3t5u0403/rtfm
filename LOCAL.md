# Local mode setup

Local mode runs entirely on your machine. No API key, no network call
to anything but your own Ollama daemon. Privacy is whatever your
laptop's privacy is.

## Steps

1. **Install Ollama:**

   ```
   curl -fsSL https://ollama.com/install.sh | sh
   ```

   Or grab a binary from <https://ollama.com/download>.

2. **Pull a model:**

   ```
   ollama pull qwen2.5-coder:7b-instruct-q4_K_M
   ```

   This is the default rtdm uses. If you want a different model, pull
   it and set `model` in `~/.config/rtdm/config.toml`.

3. **Configure rtdm:**

   ```
   rtdm config init
   ```

   Pick `local` when prompted. The defaults (Ollama on localhost:11434,
   the model above) are usually correct.

4. **Try it:**

   ```
   rtdm find files over 100mb
   ```

   The first run is slow because Ollama loads the model into memory.
   Subsequent calls are quick.

## Hardware requirements

The 7b-quant model (≈4.5 GB on disk) needs ~8 GB RAM to load. A
discrete GPU with 6+ GB VRAM gets you sub-second responses; an RTX
3060 or M2-class Apple Silicon is a comfortable floor.

CPU-only works but expect 10+ second waits. If that's painful, the
hosted service at rtdm.sh exists.

## Pointing rtdm at a remote Ollama

Useful for "Ollama on my desktop, rtdm on my laptop" setups (e.g.
over Tailscale or a LAN). Edit the config:

```toml
mode = "local"

[local]
ollama_url = "http://desktop.tailnet:11434"
model = "qwen2.5-coder:7b-instruct-q4_K_M"
```

The local backend will speak HTTP/HTTPS to whatever URL you give it —
the name "local" refers to *no third-party API*, not the network
location.

## Choosing a different model

Anything Ollama can serve will work; rtdm just sends the prompt and
streams the reply. Smaller models (e.g. `qwen2.5-coder:1.5b`) are
faster but worse at obscure commands; larger models (e.g.
`qwen2.5-coder:32b`) are slower but more reliable.

If a model produces output with markdown fences or commentary despite
the system prompt, switch to one trained more on instruction-following.
