"""<Capability name> — one discrete piece of functionality.

Public surface: run(), Input, Output. Nothing else.
See docs/CONTRACT.md for what this module promises.
"""

from ._contract import Input, Output
from ._core import build

__all__ = ["run", "Input", "Output"]


def run(data: Input) -> Output:
    """The one front door. Given an Input, return an Output.

    Does not read files, databases, or other modules — everything it
    needs is in `data`.
    """
    return build(data)
