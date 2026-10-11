"""Exceptions shared by the core. The CLI maps them to exit codes."""


class AnimaiError(Exception):
    """User-facing error: bad input, bad rig, inconsistent options (exit code 1)."""


class NotImplementedFeature(AnimaiError):
    """Feature declared in the contract but not implemented yet (exit code 2)."""
