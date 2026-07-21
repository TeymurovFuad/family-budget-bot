"""Function decorators to log entry, exit and exceptions for sync/async functions.

Usage:
    from log_decorators import log_call

    @log_call()
    def foo(...):
        ...

    @log_call()
    async def bar(...):
        ...
"""
from __future__ import annotations

import inspect
import logging
from functools import wraps
from typing import Any, Callable


def log_call(logger: logging.Logger | None = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator factory that logs entry, exit, and exceptions for a function.

    Works with both sync and async functions.
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        log = logger or logging.getLogger(func.__module__)
        name = func.__name__

        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                try:
                    log.debug("ENTER %s args=%s kwargs=%s", name, _shallow_args(args), _shallow_kwargs(kwargs))
                    result = await func(*args, **kwargs)
                    log.debug("EXIT %s result=%s", name, type(result))
                    return result
                except Exception:
                    log.exception("EXCEPTION in %s", name)
                    raise
            return async_wrapper

        else:
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                try:
                    log.debug("ENTER %s args=%s kwargs=%s", name, _shallow_args(args), _shallow_kwargs(kwargs))
                    result = func(*args, **kwargs)
                    log.debug("EXIT %s result=%s", name, type(result))
                    return result
                except Exception:
                    log.exception("EXCEPTION in %s", name)
                    raise
            return sync_wrapper

    return decorator


def _shallow_args(args: tuple) -> list:
    # Represent only first two args to avoid huge logs
    return [repr(a) for a in args[:2]]


def _shallow_kwargs(kwargs: dict) -> dict:
    return {k: repr(v) for k, v in list(kwargs.items())[:5]}
