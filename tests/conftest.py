"""Macht das Projekt-Root importierbar (Module liegen ohne src/-Layout direkt
im Repo-Root), damit `pytest` von überall aus aufgerufen werden kann."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
