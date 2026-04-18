import asyncio

from kombu.exceptions import OperationalError

from backend.task_dispatch import dispatch_or_run_inline


def test_dispatch_or_run_inline_returns_queued_when_delay_succeeds():
    calls = []

    def delay_call():
        calls.append("delay")

    result = dispatch_or_run_inline(delay_call=delay_call, inline_coro_factory=lambda: asyncio.sleep(0))

    assert result == "queued"
    assert calls == ["delay"]


def test_dispatch_or_run_inline_runs_inline_when_delay_fails(monkeypatch):
    created = []

    def fake_create_task(coro):
        created.append(coro)
        coro.close()
        return object()

    monkeypatch.setattr("backend.task_dispatch.asyncio.create_task", fake_create_task)

    result = dispatch_or_run_inline(
        delay_call=lambda: (_ for _ in ()).throw(OperationalError("redis down")),
        inline_coro_factory=lambda: asyncio.sleep(0),
    )

    assert result == "running_inline"
    assert len(created) == 1


def test_dispatch_or_run_inline_runs_inline_when_no_delay_call(monkeypatch):
    created = []

    def fake_create_task(coro):
        created.append(coro)
        coro.close()
        return object()

    monkeypatch.setattr("backend.task_dispatch.asyncio.create_task", fake_create_task)

    result = dispatch_or_run_inline(
        delay_call=None,
        inline_coro_factory=lambda: asyncio.sleep(0),
    )

    assert result == "running_inline"
    assert len(created) == 1
