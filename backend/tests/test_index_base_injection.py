from app.utils.html_base import inject_base_href

_HTML = '<!doctype html>\n<html lang="en">\n  <head>\n    <meta charset="UTF-8" />\n  </head>\n  <body></body>\n</html>\n'


def test_injects_root_base_when_empty():
    out = inject_base_href(_HTML, "")
    assert '<base href="/">' in out
    assert out.index("<base") < out.index("<meta charset")


def test_injects_prefixed_base():
    out = inject_base_href(_HTML, "/mygarage")
    assert '<base href="/mygarage/">' in out


def test_idempotent_single_base():
    once = inject_base_href(_HTML, "/mygarage")
    assert inject_base_href(once, "/mygarage").count("<base ") == 1
