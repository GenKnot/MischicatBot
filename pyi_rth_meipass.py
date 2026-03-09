import os
import sys

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    os.environ.setdefault("MISCHICAT_BASE", sys._MEIPASS)
