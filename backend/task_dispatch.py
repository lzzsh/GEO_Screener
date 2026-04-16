import asyncio
from collections.abc import Awaitable, Callable

from kombu.exceptions import OperationalError


def dispatch_or_run_inline(
    delay_call: Callable[[], object],
    inline_coro_factory: Callable[[], Awaitable[object]],
) -> str:
    try:
        delay_call()
        return "queued"
    except OperationalError:
        asyncio.create_task(inline_coro_factory())
        return "running_inline"
