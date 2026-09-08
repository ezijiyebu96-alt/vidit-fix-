"""Vidit — an offline digital brother who lives on your laptop.

This package is organised the way the Constitution describes him:

* ``soul``      – emotions, personality and his sense of self
* ``brain``     – the local LLM, memory, learning and self-repair
* ``guardian``  – permissions, boundaries and safety
* ``tools``     – search, research, files, code, system, canvas
* ``senses``    – voice (mouth), ears (STT / wake word), eyes (camera)
* ``social``    – friends and gaming companion
* ``core``      – the orchestrator that ties everything together
* ``ui``        – the body: orb, chat window, HUD, dashboard, themes
"""
from .constitution import FIRST_WORDS, NAME, VERSION

__all__ = ["NAME", "VERSION", "FIRST_WORDS"]
__version__ = VERSION
