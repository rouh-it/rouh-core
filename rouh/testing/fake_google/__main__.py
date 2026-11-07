"""Run the Google stand-in with its existing command-line interface."""
from pathlib import Path
import sys

from . import main

# Keep argparse's program name, and argv seen by the server, as the former module.
sys.argv[0] = str(Path(__file__).parent.with_suffix(".py"))
main()
