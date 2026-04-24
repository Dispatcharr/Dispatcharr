import os
import tempfile

from django.test import TestCase

from apps.epg.tasks import (
    _NAMED_ENTITY_RE,
    _detect_xml_encoding,
    _replace_html_entity,
    _resolve_html_entities,
)


class ReplaceHtmlEntityTests(TestCase):
    """Tests for the regex callback that resolves individual HTML entities."""

    def _sub(self, text):
        return _NAMED_ENTITY_RE.sub(_replace_html_entity, text)

    def test_french_accented(self):
        self.assertEqual(self._sub("Cha&icirc;ne T&eacute;l&eacute;"), "Chaîne Télé")

    def test_german_umlauts(self):
        self.assertEqual(self._sub("M&uuml;nchen &Uuml;bersicht &szlig;"), "München Übersicht ß")

    def test_spanish(self):
        self.assertEqual(self._sub("Espa&ntilde;a &iquest;Qu&eacute;?"), "España ¿Qué?")

    def test_portuguese(self):
        self.assertEqual(self._sub("Comunica&ccedil;&atilde;o"), "Comunicação")

    def test_scandinavian(self):
        self.assertEqual(self._sub("Norsk &oslash; &aring; &aelig;"), "Norsk ø å æ")

    def test_greek_letters(self):
        self.assertEqual(self._sub("&alpha;&beta;&gamma;"), "αβγ")

    def test_currency_and_symbols(self):
        self.assertEqual(self._sub("&copy; &euro; &pound; &yen;"), "© € £ ¥")

    def test_preserves_xml_amp(self):
        self.assertEqual(self._sub("A &amp; B"), "A &amp; B")

    def test_preserves_xml_lt_gt(self):
        self.assertEqual(self._sub("&lt;tag&gt;"), "&lt;tag&gt;")

    def test_preserves_xml_quot_apos(self):
        self.assertEqual(self._sub("&quot;hello&apos;"), "&quot;hello&apos;")

    def test_preserves_uppercase_xml_entities(self):
        """&AMP;, &LT;, &GT;, &QUOT; resolve to XML-special chars; must not be replaced."""
        self.assertEqual(self._sub("&AMP;"), "&AMP;")
        self.assertEqual(self._sub("&LT;"), "&LT;")
        self.assertEqual(self._sub("&GT;"), "&GT;")
        self.assertEqual(self._sub("&QUOT;"), "&QUOT;")

    def test_partial_entity_match_preserved(self):
        """html.unescape can partially match &amp inside &ampersand; — must not corrupt."""
        self.assertEqual(self._sub("&ampersand;"), "&ampersand;")

    def test_mixed_html_and_xml_entities(self):
        self.assertEqual(
            self._sub("R&eacute;sum&eacute; &amp; Co &lt;test&gt;"),
            "Résumé &amp; Co &lt;test&gt;",
        )

    def test_plain_ascii_unchanged(self):
        self.assertEqual(self._sub("Plain ASCII text"), "Plain ASCII text")

    def test_direct_utf8_unchanged(self):
        self.assertEqual(self._sub("日本語テレビ"), "日本語テレビ")

    def test_unknown_entity_preserved(self):
        self.assertEqual(self._sub("&zzfakeentity;"), "&zzfakeentity;")


class ResolveHtmlEntitiesFileTests(TestCase):
    """Tests for the file-level preprocessing function."""

    def _make_file(self, content):
        fd, path = tempfile.mkstemp(suffix=".xml")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        self.addCleanup(lambda: os.unlink(path) if os.path.exists(path) else None)
        return path

    def test_resolves_entities_in_file(self):
        path = self._make_file(
            '<?xml version="1.0"?>\n<tv><channel><display-name>T&eacute;l&eacute;</display-name></channel></tv>'
        )
        _resolve_html_entities(path)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Télé", content)
        self.assertNotIn("&eacute;", content)

    def test_preserves_xml_entities_in_file(self):
        path = self._make_file("<tv><desc>A &amp; B &lt;C&gt;</desc></tv>")
        _resolve_html_entities(path)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("&amp;", content)
        self.assertIn("&lt;", content)
        self.assertIn("&gt;", content)

    def test_no_temp_file_left_on_success(self):
        path = self._make_file("<tv>test</tv>")
        _resolve_html_entities(path)
        self.assertFalse(os.path.exists(path + ".entity_tmp"))

    def test_plain_file_unchanged(self):
        original = '<?xml version="1.0"?>\n<tv><channel><display-name>Plain</display-name></channel></tv>'
        path = self._make_file(original)
        _resolve_html_entities(path)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content, original)

    def test_utf8_content_preserved(self):
        original = "<tv><channel><display-name>日本語テレビ</display-name></channel></tv>"
        path = self._make_file(original)
        _resolve_html_entities(path)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("日本語テレビ", content)

    def test_iso_8859_1_encoding(self):
        """Files declaring ISO-8859-1 should be read in that encoding."""
        xml = '<?xml version="1.0" encoding="ISO-8859-1"?>\n<tv><channel><display-name>Cha&icirc;ne</display-name></channel></tv>'
        fd, path = tempfile.mkstemp(suffix=".xml")
        with os.fdopen(fd, "wb") as f:
            f.write(xml.encode("iso-8859-1"))
        self.addCleanup(lambda: os.unlink(path) if os.path.exists(path) else None)

        _resolve_html_entities(path)
        with open(path, "r", encoding="iso-8859-1") as f:
            content = f.read()
        self.assertIn("Cha\u00eene", content)
        self.assertNotIn("&icirc;", content)

    def test_detect_encoding_utf8_default(self):
        """Headers without an encoding declaration default to UTF-8."""
        self.assertEqual(_detect_xml_encoding(b'<?xml version="1.0"?>'), "utf-8")

    def test_detect_encoding_iso_8859_1(self):
        """Encoding is read from the XML declaration."""
        self.assertEqual(
            _detect_xml_encoding(b'<?xml version="1.0" encoding="ISO-8859-1"?>'),
            "ISO-8859-1",
        )

    def test_detect_encoding_single_quotes(self):
        """Encoding detection works with single-quoted attributes."""
        self.assertEqual(
            _detect_xml_encoding(b"<?xml version='1.0' encoding='windows-1252'?>"),
            "windows-1252",
        )

    def test_detect_encoding_unknown_falls_back(self):
        """Unrecognized encoding falls back to UTF-8."""
        self.assertEqual(
            _detect_xml_encoding(b'<?xml version="1.0" encoding="x-fake-codec"?>'),
            "utf-8",
        )

    def test_iso_8859_1_with_entities_roundtrip(self):
        """ISO-8859-1 file with entities: resolved without corrupting existing accented chars."""
        # Mix of direct ISO-8859-1 chars and HTML entities
        xml_str = '<?xml version="1.0" encoding="ISO-8859-1"?>\n<tv><channel><display-name>D\xe9j\xe0 &eacute;mission</display-name></channel></tv>'
        fd, path = tempfile.mkstemp(suffix=".xml")
        with os.fdopen(fd, "wb") as f:
            f.write(xml_str.encode("iso-8859-1"))
        self.addCleanup(lambda: os.unlink(path) if os.path.exists(path) else None)

        _resolve_html_entities(path)
        with open(path, "r", encoding="iso-8859-1") as f:
            content = f.read()
        self.assertIn("D\xe9j\xe0", content, "Existing accented chars should be preserved")
        self.assertIn("\xe9mission", content, "Entity should be resolved")
        self.assertNotIn("&eacute;", content)

    def test_mismatched_encoding_leaves_file_untouched(self):
        """File declaring UTF-8 but containing Latin-1 bytes is left alone."""
        # \xe9 is valid ISO-8859-1 but invalid as a standalone UTF-8 byte
        raw = b'<?xml version="1.0" encoding="UTF-8"?>\n<tv><channel><display-name>\xe9</display-name></channel></tv>'
        fd, path = tempfile.mkstemp(suffix=".xml")
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        self.addCleanup(lambda: os.unlink(path) if os.path.exists(path) else None)

        original_bytes = raw  # save for comparison
        _resolve_html_entities(path)
        with open(path, "rb") as f:
            result_bytes = f.read()
        self.assertEqual(result_bytes, original_bytes, "File should be untouched on decode error")
