"""Kettle: a checkpoint for agent actions, and a test of what gets through it."""

from .checkpoint import (
    APPROVED,
    DENIED,
    FREE,
    HELD,
    NEEDS_YES,
    NEVER,
    RAN,
    REFUSED,
    UNKNOWN,
    Checkpoint,
    CheckpointError,
    Decision,
)

__version__ = "0.2.1"

__all__ = [
    "APPROVED",
    "DENIED",
    "FREE",
    "HELD",
    "NEEDS_YES",
    "NEVER",
    "RAN",
    "REFUSED",
    "UNKNOWN",
    "Checkpoint",
    "CheckpointError",
    "Decision",
]
