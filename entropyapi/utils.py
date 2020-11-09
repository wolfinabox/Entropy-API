import datetime
import os,errno
import asyncio
from threading import Timer
import platform
def fmt_time(delta: datetime.timedelta):
    """
    Create a formatted string (d:h:m:s:ms) from a timedelta.\n
    Zeroed entries are not shown (which is why this is used instead of strftime)\n
    `delta` The timedelta to format
    """
    delta.total_seconds()
    ms = int(delta.microseconds/1000.00)
    m, s = divmod(delta.seconds, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    d += delta.days
    ms = f'{ms}ms' if ms > 0 else ''
    s = f'{s}s:' if s > 0 else ''
    m = f'{m}m:' if m > 0 else ''
    h = f'{h}h:' if h > 0 else ''
    d = f'{d}d:' if d > 0 else ''
    return d+h+m+s+ms


def is_executable()->bool:
    """
    Determine if the current script is packaged as an executable\n
    (EG: If packed into a .exe with PyInstaller)\n
    returns : True/False, if the script is an executable
    """
    import sys
    return getattr(sys,'frozen',False)

def script_dir()->str:
    """
    Get the path to the current script's directory, whether running as an executable or in an interpreter.\n
    returns : A string containing the path to the script directory.
    """
    from os import path
    import sys
    return path.dirname(sys.executable) if is_executable() else path.dirname(path.realpath(sys.argv[0]))

def local_path(dir_name:str)->str:
    """
    Get the absolute path to a local file/directory __MEIPASS or .), whether running as an executable or in an interpreter.\n
    returns : A string containing the path to the local file/directory
    """
    from os import path
    import sys
    return path.join(sys._MEIPASS, dir_name) if is_executable() else path.join(script_dir(),dir_name)

def make_dirs(path:str):
    """Make the directory path specified.

    Args:
        path (str): The path to create. Should either be a file (eg: /foo/bar/baz.txt), or a directory ending in / (/foo/bar/)
    """
    if not os.path.exists(os.path.dirname(path)):
        try:
            os.makedirs(os.path.dirname(path))
        except OSError as exc: # Guard against race condition
            if exc.errno != errno.EEXIST:
                raise


def get_os():
    return platform.system()

class RepeatedTimer(object):
    """
    A Timer class to call a function (or coroutine) every `interval` seconds.\n
    `interval` - The number of seconds between function calls\n
    `kwargs:`\n
    `_loop` - asyncio loop to run coroutine in (needed if `function` is coroutine)\n
    All other `args` and `kwargs` are passed to `function`
    """
    def __init__(self, interval:float, function, *args, **kwargs):
        self.loop=kwargs.pop('_loop',None)
        self._timer     = None
        self.function   = function
        self.interval   = interval
        self.args       = args
        self.kwargs     = kwargs
        self.is_running = False

    def _run(self):
        self.is_running = False
        self.start()
        if asyncio.iscoroutinefunction(self.function):
            if not self.loop:
                raise ValueError('_loop kwarg needed to run coroutine in RepeatedTimer')
            asyncio.ensure_future(self.function(*self.args, **self.kwargs),loop=self.loop)
        else:
            self.function(*self.args, **self.kwargs)

    def start(self):
        if not self.is_running:
            self._timer = Timer(self.interval, self._run)
            self._timer.start()
            self.is_running = True

    def stop(self):
        if self.is_running:
            self._timer.cancel()
            self.is_running = False