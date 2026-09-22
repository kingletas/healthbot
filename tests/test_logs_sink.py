"""The file sink is a convenience. It never decides whether the run happens."""

import re
from pathlib import Path

from healthbot import logs


def test_an_unwritable_log_directory_costs_the_file_and_not_the_run(monkeypatch, tmp_path):
    # A file where the directory should be makes makedirs raise even for root,
    # which a permission bit does not.
    (tmp_path / "not-a-directory").write_text("")
    blocked = tmp_path / "not-a-directory" / "healthbot"

    # capsys cannot see the real sink: it is enqueue=True, so it writes from
    # another thread to the stderr it captured at import.
    said = []
    sink = logs.logger.add(said.append, format="{message}", level="WARNING")

    monkeypatch.setenv("HB_LOG_DIR", str(blocked))
    try:
        assert logs.add_file_sink() is None
    finally:
        logs.logger.remove(sink)

    assert any("no log file" in line for line in said), "a lost log file must be said out loud"


def test_a_writable_directory_still_gets_its_file(monkeypatch, tmp_path):
    monkeypatch.setenv("HB_LOG_DIR", str(tmp_path / "logs"))
    sink = logs.add_file_sink()

    assert sink is not None
    assert Path(sink).parent.is_dir()
    logs.logger.remove()


def test_the_log_filename_is_a_date_a_person_can_read(monkeypatch, tmp_path):
    # loguru reads DDDD as the day of the year, so healthbot_2111326.log was
    # 22 November 2021 written as seven digits.
    monkeypatch.setenv("HB_LOG_DIR", str(tmp_path / "logs"))
    sink = logs.add_file_sink()
    logs.logger.info("a line, so the file exists")
    logs.logger.remove()

    written = next((tmp_path / "logs").iterdir()).name
    assert re.fullmatch(r"healthbot_\d{4}-\d{2}-\d{2}\.log", written), written
    assert sink is not None


def test_the_suite_never_points_at_the_real_log_directory():
    # Without tests/conftest.py this passes only by luck: importing healthbot.logs
    # resolves log_dir, and the default is the directory a real run writes to.
    from healthbot.settings import Settings, get_settings

    assert get_settings().log_dir != Settings.model_fields["log_dir"].default


def test_an_unknown_log_level_falls_back_to_info_and_says_so(monkeypatch, capsys):
    monkeypatch.setenv("HB_LOG_LEVEL", "CHATTY")

    assert logs.console_level() == "INFO"
    assert "is not a log level" in capsys.readouterr().err


def test_the_console_level_is_info_unless_asked(monkeypatch):
    monkeypatch.delenv("HB_LOG_LEVEL", raising=False)
    assert logs.console_level() == "INFO"

    monkeypatch.setenv("HB_LOG_LEVEL", "debug")
    assert logs.console_level() == "DEBUG"
