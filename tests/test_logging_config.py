import logging
import unittest

from logging_config import ConsoleFormatter


class ConsoleFormatterTestCase(unittest.TestCase):
    def test_colors_levels_and_preserves_redaction(self):
        record = logging.LogRecord(
            "test", logging.ERROR, __file__, 1, "token=secret", (), None
        )

        rendered = ConsoleFormatter("%(levelname)s %(message)s", use_color=True).format(
            record
        )

        self.assertIn("\033[31mERROR\033[0m", rendered)
        self.assertIn("token=REDACTED", rendered)

    def test_can_disable_colors(self):
        record = logging.LogRecord(
            "test", logging.INFO, __file__, 1, "hello", (), None
        )

        rendered = ConsoleFormatter("%(levelname)s %(message)s", use_color=False).format(
            record
        )

        self.assertEqual(rendered, "INFO hello")
