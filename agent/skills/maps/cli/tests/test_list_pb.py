import pytest

from gmaps_cli.list_pb import create_pb, delete_pb, ftid_halves, getlist_pb, list_index_pb, rename_pb


def test_list_index_pb_is_the_enumerate_flag():
    assert list_index_pb() == "!1e3"


def test_getlist_pb_embeds_id_and_limit_with_empty_token():
    pb = getlist_pb("LIST123", limit=500)
    assert pb == "!1m4!1sLIST123!2e2!3m1!1e1!2e2!3e2!4i500!6m3!1s!7e81!28e2!8i3!16b1"


def test_ftid_halves_splits_hex_pair_to_decimals():
    assert ftid_halves("0x2:0x3") == (2, 3)


def test_ftid_halves_rejects_malformed():
    with pytest.raises(ValueError):
        ftid_halves("nope")


def test_create_pb_encodes_name_and_carries_tokens():
    pb = create_pb("Dinner spots", token="TOK", consistency="AMAbHIx:99")
    assert pb == "!3sDinner%20spots!5m3!1sTOK!7e81!28e2!9sAMAbHIx:99"


def test_rename_pb_sets_new_name():
    pb = rename_pb("LIST", "New name", token="TOK", consistency="AMAbHIx:99")
    assert pb == "!1m4!1sLIST!2e1!3m1!1e1!2sNew%20name!4m3!1sTOK!7e81!28e2!6sAMAbHIx:99"


def test_delete_pb_targets_list():
    pb = delete_pb("LIST", token="TOK", consistency="AMAbHIx:99")
    assert pb == "!1m4!1sLIST!2e1!3m1!1e1!2m3!1sTOK!7e81!28e2!3sAMAbHIx:99"
