# dispatcharr/__init__.py

__all__ = ("celery_app",)


def __getattr__(name: str):
    if name == "celery_app":
        from .celery import app as celery_app

        return celery_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
