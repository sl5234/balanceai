from balanceai_backend.db import connection
from balanceai_backend.paths import SECRETS_DIR


def test_tests_never_use_the_real_data_folder():
    assert connection.DATA_DIR.resolve() != (SECRETS_DIR / "data").resolve()
