"""Subprocess helpers that keep the GUI free of stray console windows."""

from __future__ import annotations

import os
import subprocess
from typing import Any

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def run_hidden(args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
    kwargs.setdefault("creationflags", CREATE_NO_WINDOW)
    return subprocess.run(args, **kwargs)
