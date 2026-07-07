"""Tests for HTML entity resolution in XMLTV parsing (DOCTYPE injection path)."""

import os
import tempfile

from django.test import TestCase
from lxml import etree

from apps.epg.tasks import _open_xmltv_file, _parse_programme_element


def _parse_title(entity_text: str) -> str:
    """Resolve entities the same way production programme parsing does."""
    xml = (
        f'<programme start="20000101000000 +0000" '
        f'stop="20000101000000 +0000" channel="test.ch">'
        f"<title>{entity_text}</title></programme>"
    ).encode("utf-8")
    root = _parse_programme_element(xml)
    return root.findtext("title")


def _read_display_name_from_file(path: str) -> str:
    with _open_xmltv_file(path) as handle:
        for _event, elem in etree.iterparse(handle, events=("end",), tag="display-name"):
            text = (elem.text or "").strip()
            elem.clear()
            while elem.getprevious() is not None:
                del elem.getparent()[0]
            return text
    return ""


class ParseProgrammeElementEntityTests(TestCase):
    """Entity resolution via _parse_programme_element + injected DOCTYPE."""

    def test_french_accented(self):
        self.assertEqual(_parse_title("Cha&icirc;ne T&eacute;l&eacute;"), "Chaîne Télé")

    def test_german_umlauts(self):
        self.assertEqual(
            _parse_title("M&uuml;nchen &Uuml;bersicht &szlig;"),
            "München Übersicht ß",
        )

    def test_spanish(self):
        self.assertEqual(_parse_title("Espa&ntilde;a &iquest;Qu&eacute;?"), "España ¿Qué?")

    def test_portuguese(self):
        self.assertEqual(_parse_title("Comunica&ccedil;&atilde;o"), "Comunicação")

    def test_scandinavian(self):
        self.assertEqual(_parse_title("Norsk &oslash; &aring; &aelig;"), "Norsk ø å æ")

    def test_greek_letters(self):
        self.assertEqual(_parse_title("&alpha;&beta;&gamma;"), "αβγ")

    def test_currency_and_symbols(self):
        self.assertEqual(_parse_title("&copy; &euro; &pound; &yen;"), "© € £ ¥")

    def test_preserves_xml_amp(self):
        self.assertEqual(_parse_title("A &amp; B"), "A & B")

    def test_preserves_xml_lt_gt(self):
        self.assertEqual(_parse_title("&lt;tag&gt;"), "<tag>")

    def test_preserves_xml_quot_apos(self):
        self.assertEqual(_parse_title("&quot;hello&apos;"), '"hello\'')

    def test_mixed_html_and_xml_entities(self):
        self.assertEqual(
            _parse_title("R&eacute;sum&eacute; &amp; Co &lt;test&gt;"),
            "Résumé & Co <test>",
        )

    def test_plain_ascii_unchanged(self):
        self.assertEqual(_parse_title("Plain ASCII text"), "Plain ASCII text")

    def test_direct_utf8_unchanged(self):
        self.assertEqual(_parse_title("日本語テレビ"), "日本語テレビ")


class OpenXmltvFileEntityTests(TestCase):
    """Entity resolution via _open_xmltv_file streaming (no disk rewrite)."""

    def _make_file(self, content, *, binary=False):
        fd, path = tempfile.mkstemp(suffix=".xml")
        with os.fdopen(fd, "wb" if binary else "w", encoding=None if binary else "utf-8") as f:
            f.write(content)
        self.addCleanup(lambda: os.unlink(path) if os.path.exists(path) else None)
        return path

    def test_resolves_entities_in_file(self):
        path = self._make_file(
            '<?xml version="1.0"?>\n'
            "<tv><channel><display-name>T&eacute;l&eacute;</display-name></channel></tv>"
        )
        self.assertEqual(_read_display_name_from_file(path), "Télé")
        with open(path, "r", encoding="utf-8") as f:
            self.assertIn("&eacute;", f.read(), "Source file must not be rewritten on disk")

    def test_preserves_xml_entities_in_file(self):
        path = self._make_file("<tv><channel><display-name>A &amp; B</display-name></channel></tv>")
        self.assertEqual(_read_display_name_from_file(path), "A & B")

    def test_plain_file_unchanged_on_disk(self):
        original = (
            '<?xml version="1.0"?>\n'
            "<tv><channel><display-name>Plain</display-name></channel></tv>"
        )
        path = self._make_file(original)
        _read_display_name_from_file(path)
        with open(path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), original)

    def test_utf8_content_preserved(self):
        path = self._make_file(
            "<tv><channel><display-name>日本語テレビ</display-name></channel></tv>"
        )
        self.assertEqual(_read_display_name_from_file(path), "日本語テレビ")

    def test_iso_8859_1_encoding(self):
        xml = (
            '<?xml version="1.0" encoding="ISO-8859-1"?>\n'
            "<tv><channel><display-name>Cha&icirc;ne</display-name></channel></tv>"
        )
        path = self._make_file(xml.encode("iso-8859-1"), binary=True)
        self.assertEqual(_read_display_name_from_file(path), "Cha\u00eene")

    def test_iso_8859_1_with_entities_roundtrip(self):
        xml_str = (
            '<?xml version="1.0" encoding="ISO-8859-1"?>\n'
            "<tv><channel><display-name>D\xe9j\xe0 &eacute;mission</display-name></channel></tv>"
        )
        path = self._make_file(xml_str.encode("iso-8859-1"), binary=True)
        name = _read_display_name_from_file(path)
        self.assertIn("D\xe9j\xe0", name)
        self.assertIn("\xe9mission", name)

    def test_existing_doctype_not_doubled(self):
        """Files that already declare DOCTYPE are opened without injecting another."""
        path = self._make_file(
            '<!DOCTYPE tv SYSTEM "xmltv.dtd">\n'
            "<tv><channel><display-name>Has Doctype</display-name></channel></tv>"
        )
        with open(path, "rb") as f:
            original = f.read()
        with _open_xmltv_file(path) as handle:
            self.assertEqual(handle.read(len(original)), original)
