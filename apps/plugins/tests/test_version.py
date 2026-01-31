"""Tests for version compatibility checking."""

from unittest import TestCase
from unittest.mock import patch


class TestCheckCompatibility(TestCase):
    """Test cases for the check_compatibility function."""

    def test_compatible_minimum_version(self):
        """Test that current version satisfies minimum constraint."""
        with patch("apps.plugins.version.__version__", "0.18.1"):
            from apps.plugins.version import check_compatibility

            compatible, error = check_compatibility(">=0.18.0")
            self.assertTrue(compatible)
            self.assertEqual(error, "")

    def test_compatible_exact_minimum(self):
        """Test when current version exactly matches minimum."""
        with patch("apps.plugins.version.__version__", "0.18.0"):
            from apps.plugins.version import check_compatibility

            compatible, error = check_compatibility(">=0.18.0")
            self.assertTrue(compatible)
            self.assertEqual(error, "")

    def test_incompatible_below_minimum(self):
        """Test that older version fails minimum constraint."""
        with patch("apps.plugins.version.__version__", "0.17.0"):
            from apps.plugins.version import check_compatibility

            compatible, error = check_compatibility(">=0.18.0")
            self.assertFalse(compatible)
            self.assertIn("Requires Dispatcharr >=0.18.0", error)
            self.assertIn("0.17.0", error)

    def test_incompatible_high_requirement(self):
        """Test plugin requiring future version."""
        with patch("apps.plugins.version.__version__", "0.18.1"):
            from apps.plugins.version import check_compatibility

            compatible, error = check_compatibility(">=0.20.0")
            self.assertFalse(compatible)
            self.assertIn("Requires Dispatcharr >=0.20.0", error)

    def test_compatible_range(self):
        """Test version within range constraint."""
        with patch("apps.plugins.version.__version__", "0.18.5"):
            from apps.plugins.version import check_compatibility

            compatible, error = check_compatibility(">=0.18.0,<0.19.0")
            self.assertTrue(compatible)
            self.assertEqual(error, "")

    def test_incompatible_above_range(self):
        """Test version above range maximum."""
        with patch("apps.plugins.version.__version__", "0.19.0"):
            from apps.plugins.version import check_compatibility

            compatible, error = check_compatibility(">=0.18.0,<0.19.0")
            self.assertFalse(compatible)
            self.assertIn("Requires Dispatcharr >=0.18.0,<0.19.0", error)

    def test_compatible_exact_version(self):
        """Test exact version match."""
        with patch("apps.plugins.version.__version__", "0.18.0"):
            from apps.plugins.version import check_compatibility

            compatible, error = check_compatibility("==0.18.0")
            self.assertTrue(compatible)
            self.assertEqual(error, "")

    def test_incompatible_exact_version(self):
        """Test exact version mismatch."""
        with patch("apps.plugins.version.__version__", "0.18.1"):
            from apps.plugins.version import check_compatibility

            compatible, error = check_compatibility("==0.18.0")
            self.assertFalse(compatible)

    def test_compatible_release(self):
        """Test compatible release (~=) operator."""
        with patch("apps.plugins.version.__version__", "0.18.5"):
            from apps.plugins.version import check_compatibility

            # ~=0.18.0 means >=0.18.0, <0.19.0
            compatible, error = check_compatibility("~=0.18.0")
            self.assertTrue(compatible)
            self.assertEqual(error, "")

    def test_incompatible_release(self):
        """Test compatible release fails for next minor."""
        with patch("apps.plugins.version.__version__", "0.19.0"):
            from apps.plugins.version import check_compatibility

            compatible, error = check_compatibility("~=0.18.0")
            self.assertFalse(compatible)

    def test_invalid_specifier_syntax(self):
        """Test invalid constraint syntax returns error."""
        with patch("apps.plugins.version.__version__", "0.18.0"):
            from apps.plugins.version import check_compatibility

            compatible, error = check_compatibility(">=>0.18.0")
            self.assertFalse(compatible)
            self.assertIn("Invalid version constraint", error)

    def test_invalid_constraint_missing_version(self):
        """Test constraint with missing version number."""
        with patch("apps.plugins.version.__version__", "0.18.0"):
            from apps.plugins.version import check_compatibility

            compatible, error = check_compatibility(">=")
            self.assertFalse(compatible)
            self.assertIn("Invalid version constraint", error)

    def test_less_than_constraint(self):
        """Test less-than constraint."""
        with patch("apps.plugins.version.__version__", "0.17.0"):
            from apps.plugins.version import check_compatibility

            compatible, error = check_compatibility("<0.18.0")
            self.assertTrue(compatible)
            self.assertEqual(error, "")

    def test_not_equal_constraint(self):
        """Test not-equal constraint."""
        with patch("apps.plugins.version.__version__", "0.18.1"):
            from apps.plugins.version import check_compatibility

            compatible, error = check_compatibility("!=0.18.0")
            self.assertTrue(compatible)
            self.assertEqual(error, "")
