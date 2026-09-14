import configparser
import unittest

import config


class WebConfigurationTestCase(unittest.TestCase):
    def setUp(self):
        self._config_data = config.config_data
        config.config_data = configparser.ConfigParser()

    def tearDown(self):
        config.config_data = self._config_data

    def test_web_api_key_must_be_at_least_32_characters(self):
        for value in ("", "short-key"):
            config.config_data.read_dict({"web": {"api_key": value}})
            with self.subTest(value=value), self.assertRaises(SystemExit):
                config._get_web_api_key()
            config.config_data.clear()

    def test_web_api_key_is_trimmed(self):
        key = "a" * 32
        config.config_data.read_dict({"web": {"api_key": f"  {key}  "}})
        self.assertEqual(config._get_web_api_key(), key)


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
