"""Explicit allowlist of first-party Celery tasks callable by plugins."""
from typing import Any, Dict, Iterable, Mapping, Optional


_PLUGIN_TASKS: Dict[str, Any] = {}


def plugin_callable_task(task: Any) -> Any:
    """Register a Celery task as safe for plugin dispatch."""
    _PLUGIN_TASKS[task.name] = task
    return task


def dispatch_plugin_task(
    task_name: str,
    args: Optional[Iterable[Any]] = None,
    kwargs: Optional[Mapping[str, Any]] = None,
) -> Any:
    """Queue an explicitly registered task on the isolated plugins queue."""
    task = _PLUGIN_TASKS.get(task_name)
    if task is None:
        raise ValueError(f"Plugin dispatch requested unapproved task '{task_name}'.")
    if args is not None and not isinstance(args, (list, tuple)):
        raise ValueError("Plugin task args must be a list or tuple.")
    if kwargs is not None and not isinstance(kwargs, Mapping):
        raise ValueError("Plugin task kwargs must be a mapping.")
    return task.apply_async(
        args=() if args is None else args,
        kwargs={} if kwargs is None else dict(kwargs),
        queue="plugins",
    )
