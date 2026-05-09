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

from __future__ import annotations

import re

# Strip C0 (except \t, \n, \r) and C1 control characters from model
# output before display or further processing.  A malicious or
# compromised model could otherwise smuggle ANSI escape sequences
# (e.g. cursor manipulation, line erasure) that overwrite the y/N
# confirmation prompt or the command being shown to the user.
# We allow \t (\x09), \n (\x0A), \r (\x0D); everything else in the
# C0/C1 ranges is removed.
_CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]")


def strip_control_chars(text: str) -> str:
    """Remove C0/C1 control characters from ``text`` (preserves \\t, \\n, \\r)."""
    return _CONTROL_CHAR_PATTERN.sub("", text)
