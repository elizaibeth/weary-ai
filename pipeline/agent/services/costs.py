"""Token, time and dollar cost for one `daily.run()` call.

Only reports numbers an API actually gave us. TypeSafe returns token counts
but never a dollar figure, so it is reported as tokens only; Runware returns
a real dollar cost for both images and text generation. Nothing is estimated.

Costs are recorded only by the shell modules that call paid services (`llm`,
`verifier` and `illustrator`), never by the pure cores. They go to the
tracker that `daily.run` opens with `tracking()`; outside a run (for example
in a unit test of one client), recording does nothing.
"""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class RunCosts:
    started_at: float = field(default_factory=time.monotonic)
    text_prompt_tokens: int = 0
    text_completion_tokens: int = 0
    text_usd: float = 0.0
    typesafe_input_tokens: int = 0
    typesafe_output_tokens: int = 0
    image_usd: float = 0.0
    image_calls: int = 0

    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.started_at


_active: ContextVar[RunCosts | None] = ContextVar("weary_run_costs", default=None)


@contextmanager
def tracking() -> Iterator[RunCosts]:
    """Collect every cost recorded inside the block into one fresh `RunCosts`."""
    run = RunCosts()
    token = _active.set(run)
    try:
        yield run
    finally:
        _active.reset(token)


def record_text_usage(usage: dict) -> None:
    if run := _active.get():
        run.text_prompt_tokens += usage.get("prompt_tokens", 0) or 0
        run.text_completion_tokens += usage.get("completion_tokens", 0) or 0


def record_text_cost(usd) -> None:
    if (run := _active.get()) and usd:
        run.text_usd += usd


def record_typesafe(usage) -> None:
    if run := _active.get():
        run.typesafe_input_tokens += getattr(usage, "input_tokens", None) or 0
        run.typesafe_output_tokens += getattr(usage, "output_tokens", None) or 0


def record_image_cost(usd) -> None:
    if run := _active.get():
        if usd:
            run.image_usd += usd
        run.image_calls += 1
