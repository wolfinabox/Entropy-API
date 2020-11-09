import os
from typing import Any
from sqlitedict import SqliteDict
import daiquiri
logger=daiquiri.getLogger('entropy.cache')
from .utils import script_dir,make_dirs
cache_path=os.path.join(script_dir(),'data','entropy_cache.db')
logger.info(f'Opened database "{cache_path}"')
make_dirs(cache_path)
_cache=SqliteDict(cache_path,autocommit=False)

def cache_get(key:Any,default:Any=None)->Any:
    """Get a value from the cache. Works like dict.get()

    Args:
        key (Any): Key to access
        default (Any, optional): Value to return if key not found. Defaults to None.

    Returns:
        Any: The value, or None
    """
    global _cache
    if key in _cache:
        logger.debug(f'Cache hit for key "{key}"')
        return _cache[key]
    else: return default

def cache_set(key:Any,val:Any,commit:bool=True,blocking_commit=False):
    """Set a value in the cache.

    Args:
        key (Any): The key to set the value of
        val (Any): The value to set
        commit (bool, optional): Whether or not to commit the change to disk. Defaults to True.
        blocking_commit (bool, optional): Whether or not the commit is blocking or queued. Defaults to False.
    """
    global _cache
    _cache[key]=val
    if commit:
        _cache.commit(blocking_commit)
    logger.debug(f'Saved key "{key}" to cache')

def cache_set_dict(d:dict,commit:bool=True,blocking_commit=False):
    """Set keys/values in the cache to the keys/values in the dict.
        Functions the same as dict.update()

    Args:
        d (dict): The dict to get keys/values from
        commit (bool, optional): [description]. Defaults to True.
        blocking_commit (bool, optional): [description]. Defaults to False.
    """
    _cache.update(d)
    if commit:
        _cache.commit(blocking_commit)
    logger.debug(f'Saved {len(d)} keys/vals from dict to cache')