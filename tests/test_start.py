import unittest
from unittest.mock import patch

import start


class FakeProcess:
    def __init__(self, name, exitcode=None):
        self.name = name
        self.exitcode = exitcode
        self.pid = None
        self.sentinel = object()
        self.terminated = False
        self.joined = False

    def start(self):
        self.pid = 123

    def is_alive(self):
        return self.exitcode is None

    def terminate(self):
        self.terminated = True
        self.exitcode = -15

    def join(self):
        self.joined = True


class LauncherTestCase(unittest.TestCase):
    def test_child_failure_is_propagated_and_sibling_is_stopped(self):
        failed = FakeProcess("discord-bot", exitcode=7)
        sibling = FakeProcess("registration-webhook")

        with patch.object(start, "wait", return_value=[failed.sentinel]):
            exit_code = start.run_processes((failed, sibling))

        self.assertEqual(exit_code, 7)
        self.assertTrue(sibling.terminated)
        self.assertTrue(failed.joined)
        self.assertTrue(sibling.joined)

    def test_unexpected_clean_child_exit_is_failure(self):
        exited = FakeProcess("discord-bot", exitcode=0)
        sibling = FakeProcess("registration-webhook")

        with patch.object(start, "wait", return_value=[exited.sentinel]):
            self.assertEqual(start.run_processes((exited, sibling)), 1)
