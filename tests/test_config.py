import configparser
import unittest

import config


class CleanupConfigurationTestCase(unittest.TestCase):
    def setUp(self):
        self._config_data = config.config_data
        config.config_data = configparser.ConfigParser()

    def tearDown(self):
        config.config_data = self._config_data

    def load(self, value=None, *, option="channel_ids"):
        config.config_data.read_dict({"cleanup": {option: value or ""}})
        return config._get_int_set("cleanup", option)

    def test_missing_cleanup_section_is_empty(self):
        self.assertEqual(config._get_int_set("cleanup", "channel_ids"), set())

    def test_empty_values_are_empty(self):
        self.assertEqual(self.load("  \t"), set())

    def test_ids_are_parsed_trimmed_and_deduplicated(self):
        self.assertEqual(self.load("1, 2, 1, 3"), {1, 2, 3})

    def test_invalid_ids_fail_configuration_loading(self):
        for value in ("abc", "0", "-1", "1,,2"):
            with self.subTest(value=value), self.assertRaises(SystemExit):
                self.load(value)
