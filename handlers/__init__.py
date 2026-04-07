from handlers.commands import router as commands_router
from handlers.messages import router as messages_router
from handlers.callbacks import router as callbacks_router

__all__ = [
    "commands_router",
    "messages_router",
    "callbacks_router",
]
