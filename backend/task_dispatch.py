import asyncio
from collections.abc import Awaitable, Callable
from typing import Optional

from kombu.exceptions import OperationalError


def dispatch_or_run_inline(
    delay_call: Optional[Callable[[], object]],
    inline_coro_factory: Callable[[], Awaitable[object]],
) -> str:
    if delay_call is None:
        asyncio.create_task(inline_coro_factory())
        return "running_inline"
    try:
        delay_call()
        return "queued"
    except OperationalError:
        asyncio.create_task(inline_coro_factory())
        return "running_inline"
