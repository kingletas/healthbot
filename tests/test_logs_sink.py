"""The file sink is a convenience. It never decides whether the run happens."""

from pathlib import Path

from healthbot import logs


def test_an_unwritable_log_directory_costs_the_file_and_not_the_run(monkeypatch, tmp_path):
    # A container running as a system account with no home, or a read-only
    # install: makedirs raises, and importing the package used to die with it.
    blocked = tmp_path / "read-only" / "healthbot"
    (tmp_path / "read-only").mkdir()
    (tmp_path / "read-only").chmod(0o500)

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
