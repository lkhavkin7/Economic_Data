"""Makes `python -m src.econ_data` run the command line interface."""
import sys

from .cli import main

sys.exit(main())