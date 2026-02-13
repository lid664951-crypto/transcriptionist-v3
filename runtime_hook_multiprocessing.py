import sys
import multiprocessing
if sys.platform == 'win32':
    multiprocessing.set_start_method('spawn', force=True)
