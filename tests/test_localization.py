from html.parser import HTMLParser

import pytest

from polysentinel.localization import localize_html
from polysentinel.storage import Store
from polysentinel.web import create_app


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = False
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = False

    def handle_data(self, data):
        if not self.skip:
            self.text.append(data)


@pytest.fixture
def client(tmp_path):
    return create_app(store=Store(tmp_path / "localized.sqlite3")).test_client()


@pytest.mark.parametrize(
    "route",
    [
        "/",
        "/insider",
        "/transfers",
        "/funding",
        "/documentation",
        "/dev",
        "/about",
        "/disclaimer",
    ],
)
def test_language_toggle_on_every_page(client, route):
    response = client.get(route + "?lang=pt-BR")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '<html lang="pt-BR">' in html
    assert 'data-language-link="true"' in html
    assert ">English</a>" in html
    assert ">PT-BR</a>" in html
    assert response.headers["Content-Language"] == "pt-BR"
    assert "sentinel_language=pt-BR" in response.headers["Set-Cookie"]
    assert '<html lang="pt-BR">' in client.get(route).get_data(as_text=True)
    assert '<html lang="en">' in client.get(route + "?lang=en").get_data(as_text=True)


@pytest.mark.parametrize(
    "route,en,pt",
    [
        ("/", "Latest large bets", "Últimas apostas grandes"),
        ("/insider", "No flagged wallets yet", "Nenhuma carteira sinalizada ainda"),
        ("/transfers", "Transfer explorer", "Explorador de transferências"),
        (
            "/dev",
            "Currently open to new opportunities",
            "Disponível para novas oportunidades",
        ),
        ("/about", "About", "Sobre"),
        ("/disclaimer", "Portfolio project.", "Projeto de portfólio."),
        ("/documentation", "Observed activity", "Atividade observada"),
    ],
)
def test_only_selected_language_visible(client, route, en, pt):
    for language, expected, absent in [("en", en, pt), ("pt-BR", pt, en)]:
        parser = VisibleText()
        parser.feed(client.get(route + "?lang=" + language).get_data(as_text=True))
        visible = "".join(parser.text)
        assert expected in visible
        assert absent not in visible


def test_toggle_preserves_wallet_and_rejects_invalid_language(client):
    address = "0x" + "a" * 40
    html = client.get("/transfers?address=" + address + "&lang=pt-BR").get_data(
        as_text=True
    )
    assert "address=" + address + "&amp;lang=en" in html
    assert '<html lang="pt-BR">' in client.get("/?lang=invalid").get_data(as_text=True)
    assert "Set-Cookie" not in client.get("/?lang=invalid").headers


def test_localizer_preserves_scripts_attributes_and_escaping():
    html = '<div><p lang="en">English</p><p lang="pt-BR">Português <strong>texto</strong></p><input placeholder="Filter markets"/><script>const s = "Dashboard <foo>";</script><span>&lt;img&gt;</span></div>'
    result = localize_html(html, "pt-BR")
    assert "English" not in result
    assert "Português <strong>texto</strong>" in result
    assert 'placeholder="Filtrar mercados"' in result
    assert '<script>const s = "Dashboard <foo>";</script>' in result
    assert "&lt;img&gt;" in result
