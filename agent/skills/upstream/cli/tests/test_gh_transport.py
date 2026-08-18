import json

from upstream_cli import cli

SENTINEL = "ghs_SENTINELtoken1234567890abcdef"


def test_gh_env_injects_token_and_repo():
    env = cli.gh_env(SENTINEL)
    assert env["GH_TOKEN"] == SENTINEL
    assert env["GH_REPO"] == "elyxlz/vesta"


def test_gh_api_puts_the_token_in_env_never_argv(fake_gh):
    record, response = fake_gh
    response.write_text(json.dumps({"ok": True}))
    code, out = cli.gh_api(SENTINEL, "repos/elyxlz/vesta/pulls/1")
    seen = json.loads(record.read_text())
    assert code == 0
    assert json.loads(out) == {"ok": True}
    assert seen["env"]["GH_TOKEN"] == SENTINEL
    assert SENTINEL not in " ".join(seen["argv"])
    assert seen["argv"][0] == "api"


def test_gh_api_post_sends_fields(fake_gh):
    record, _ = fake_gh
    cli.gh_api(SENTINEL, "repos/elyxlz/vesta/issues", method="POST", fields={"title": "t", "body": "b"})
    seen = json.loads(record.read_text())
    assert seen["argv"][:3] == ["api", "-X", "POST"]
    assert "title=t" in seen["argv"] and "body=b" in seen["argv"]
