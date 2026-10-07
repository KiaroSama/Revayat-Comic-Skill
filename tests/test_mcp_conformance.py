"""Legacy tool dispatch follows protocol errors, not business outcomes."""
import pytest
import server


@pytest.mark.parametrize("name", ["revayat_missing", None, [], {}, True, "doctor"])
def test_unknown_tool_is_invalid_params_and_session_survives(name):
    response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                              "params": {"name": name}})
    assert response["error"]["code"] == -32602
    assert server.handle({"jsonrpc": "2.0", "id": 2, "method": "ping"}) == {
        "jsonrpc": "2.0", "id": 2, "result": {}}
