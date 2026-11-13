import re

import pytest
from balanceai_backend.utils.general_util import IdPrefix, generate_id


@pytest.mark.parametrize("prefix", list(IdPrefix))
def test_generate_id_has_the_prefix_and_32_hex_characters(prefix):
    assert re.fullmatch(rf"{prefix.value}-[0-9a-f]{{32}}", generate_id(prefix))


def test_generate_id_is_unique():
    assert generate_id(IdPrefix.RECEIPT) != generate_id(IdPrefix.RECEIPT)
