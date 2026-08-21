import pytest

from gmaps_cli.list_pb import ftid_halves, getlist_pb, list_index_pb


def test_list_index_pb_is_the_enumerate_flag():
    assert list_index_pb() == "!1e3"


def test_getlist_pb_embeds_id_token_and_limit():
    pb = getlist_pb("LIST123", "TOK456", limit=500)
    assert pb == "!1m4!1sLIST123!2e2!3m1!1e1!2e2!3e2!4i500!6m3!1sTOK456!7e81!28e2!8i3!16b1"


def test_ftid_halves_splits_hex_pair_to_decimals():
    assert ftid_halves("0x2:0x3") == (2, 3)


def test_ftid_halves_rejects_malformed():
    with pytest.raises(ValueError):
        ftid_halves("nope")
