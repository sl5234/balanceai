from enum import Enum


class Bank(str, Enum):
    CHASE = "chase"
    MARCUS = "marcus"
    COINBASE = "coinbase"
    WEBULL = "webull"
