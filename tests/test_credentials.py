from uuid import uuid4

import pytest
from daz_secrets import Client, DazSecretsError, ErrorCode


def test_real_provider_round_trip() -> None:
    client = Client()
    account = f"test/{uuid4()}"
    try:
        client.set("map-generator", account, b"provider-value")
        assert client.get("map-generator", account).value == b"provider-value"
        client.delete("map-generator", account)
        with pytest.raises(DazSecretsError) as caught:
            client.get("map-generator", account)
        assert caught.value.code is ErrorCode.NOT_FOUND
    finally:
        try:
            client.delete("map-generator", account)
        except DazSecretsError as error:
            if error.code is not ErrorCode.NOT_FOUND:
                raise
