"""Backend implementations for the rtdm CLI.

Two backends share the same three-function shape so the dispatcher
in ``rtdm.main`` can swap them transparently:

* :func:`query`  — natural language → single shell command
* :func:`ask`    — free-form terminal question → plain-English answer
* :func:`explain`— shell command → plain-English breakdown

The local backend streams tokens from a user-run Ollama instance.  The
remote backend POSTs to ``rtdm.sh`` and prints the full response on
completion.  Streaming over HTTPS is intentionally deferred.
"""
