"""A recording stand-in for camoufox.sync_api.Camoufox: enough Playwright surface for the worker's helpers."""

import json
import pathlib as pl


class _Mouse:
    def __init__(self, log):
        self.log = log

    def click(self, x, y, button="left", click_count=1):
        self.log.append(("click", x, y, button, click_count))

    def move(self, x, y):
        self.log.append(("move", x, y))

    def wheel(self, dx, dy):
        self.log.append(("wheel", dx, dy))


class _Keyboard:
    def __init__(self, log):
        self.log = log

    def type(self, text):
        self.log.append(("type", text))

    def press(self, key):
        self.log.append(("press", key))


class FakePage:
    def __init__(self, context, url="about:blank"):
        self.context = context
        self.url = url
        self._title = "blank"
        self.log = context.log
        self.mouse = _Mouse(self.log)
        self.keyboard = _Keyboard(self.log)
        self.closed = False

    def goto(self, url, **_):
        self.url = url
        self._title = "Title of " + url
        self.log.append(("goto", url))

    def title(self):
        return self._title

    def evaluate(self, expression, arg=None):
        self.log.append(("evaluate", expression))
        if expression.startswith("() => ({"):
            return {"url": self.url, "title": self._title, "w": 1280, "h": 800, "sx": 0, "sy": 0, "pw": 1280, "ph": 2000}
        if expression == "1 + 1":
            return 2
        if expression == "throw":
            raise RuntimeError("Evaluation failed: boom")
        return None

    def fill(self, selector, text, timeout=None, **_):
        self.log.append(("fill", selector, text))

    def wait_for_load_state(self, state="load", timeout=None):
        self.log.append(("wait_for_load_state", state))

    def wait_for_selector(self, selector, state="attached", timeout=None):
        self.log.append(("wait_for_selector", selector, state))
        if selector == "#never":
            raise TimeoutError("timeout")

    def screenshot(self, path=None, full_page=False):
        pl.Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 8)
        self.log.append(("screenshot", path, full_page))

    def set_input_files(self, selector, path):
        self.log.append(("upload", selector, path))

    def bring_to_front(self):
        self.log.append(("front", self.url))

    def close(self):
        self.closed = True
        self.context.pages.remove(self)


class FakeContext:
    def __init__(self):
        self.log = []
        self.pages = [FakePage(self)]

    def new_page(self):
        page = FakePage(self)
        self.pages.append(page)
        return page


class Camoufox:
    """Records launch options to `<user_data_dir>/launch.json` so a test can assert them."""

    def __init__(self, **options):
        self.options = options

    def __enter__(self):
        pl.Path(self.options["user_data_dir"], "launch.json").write_text(json.dumps({k: str(v) for k, v in self.options.items()}))
        return FakeContext()

    def __exit__(self, *exc):
        return False
