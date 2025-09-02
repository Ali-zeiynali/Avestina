import logging
from dataclasses import dataclass

@dataclass
class BotState:
    store_memory: bool = True
    send_history: bool = True
    debug: bool = False

state = BotState()

logger = logging.getLogger("avestina")
_handler = logging.StreamHandler()
_formatter = logging.Formatter("%(levelname)s:%(name)s:%(message)s")
_handler.setFormatter(_formatter)
logger.addHandler(_handler)
logger.setLevel(logging.WARNING)


def set_debug(enabled: bool) -> None:
    state.debug = enabled
    logger.setLevel(logging.DEBUG if enabled else logging.WARNING)
