__version__ = "0.0.0"
from pathlib import Path
print("'" + Path(__file__).stem + ".py'  v" + __version__)

from time import perf_counter
t_start_sec = perf_counter()

import os
import sys
from pathlib import Path

