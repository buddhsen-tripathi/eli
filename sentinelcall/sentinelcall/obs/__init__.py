"""Observability package.

Import the module (`from sentinelcall.obs import trace`) and call
`trace.line(...)`, `trace.turn(...)`, etc. We deliberately do NOT re-export the
submodule members by name here, so `import trace` always resolves to the
submodule and never gets shadowed by a same-named function.
"""

from . import trace  # noqa: F401

__all__ = ["trace"]
