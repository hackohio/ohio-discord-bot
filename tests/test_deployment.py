import os
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DatabaseRestoreTestCase(unittest.TestCase):
    def test_restore_step_stops_on_download_errors(self):
        workflow = (ROOT / ".github/workflows/bot-start.yml").read_text()
        script = textwrap.dedent(
            re.search(
                r"- name: Download database backup\n.*?run: \|\n(.*?)(?=\n      #)",
                workflow,
                re.DOTALL,
            ).group(1)
        )
        cases = (
            (0, ""),
            (1, "NoSuchKey"),
            (254, "AccessDenied"),
            (255, "Connection error"),
        )
        for exit_code, error in cases:
            with (
                self.subTest(error=error or "success"),
                tempfile.TemporaryDirectory() as tmp,
            ):
                directory = Path(tmp)
                aws = directory / "aws"
                aws.write_text(
                    "#!/bin/sh\n"
                    'if [ "$AWS_EXIT_CODE" != 0 ]; then\n'
                    '  echo "$AWS_ERROR" >&2\n'
                    '  exit "$AWS_EXIT_CODE"\n'
                    "fi\n"
                    'if [ "$1" = s3 ]; then printf "backup" > "$4"; fi\n'
                )
                aws.chmod(0o700)
                env_file = directory / "github-env"
                env_file.touch()
                result = subprocess.run(
                    ["bash", "-e", "-o", "pipefail", "-c", script],
                    env={
                        **os.environ,
                        "PATH": f"{directory}:{os.environ['PATH']}",
                        "AWS_EXIT_CODE": str(exit_code),
                        "AWS_ERROR": error,
                        "BACKUP_BUCKET": "test-backups",
                        "EVENT": "test-event",
                        "RUNNER_TEMP": tmp,
                        "GITHUB_ENV": str(env_file),
                    },
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertEqual(result.returncode, exit_code)
                if exit_code:
                    self.assertEqual(env_file.read_text(), "")
                    self.assertIn(error, result.stderr)
                else:
                    self.assertEqual((directory / "records.db").read_text(), "backup")
                    self.assertEqual(
                        env_file.read_text(), f"RESTORE_DB_FILE={tmp}/records.db\n"
                    )
