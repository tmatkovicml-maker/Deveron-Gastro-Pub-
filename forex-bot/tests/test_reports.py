from datetime import datetime, timedelta, timezone

from forexbot.reports import last_scheduled
from tests.test_grid import FakeEx, make_grid

UTC = timezone.utc


def test_last_scheduled_sunday_evening():
    # srijeda 12.11.2025 -> zadnja nedjelja 9.11. u 19h
    assert last_scheduled(datetime(2025, 11, 12, 10, tzinfo=UTC), 6, 19) == datetime(2025, 11, 9, 19, tzinfo=UTC)
    # nedjelja prije 19h -> prošla nedjelja
    assert last_scheduled(datetime(2025, 11, 16, 18, tzinfo=UTC), 6, 19) == datetime(2025, 11, 9, 19, tzinfo=UTC)
    # nedjelja nakon 19h -> danas
    assert last_scheduled(datetime(2025, 11, 16, 19, 5, tzinfo=UTC), 6, 19) == datetime(2025, 11, 16, 19, tzinfo=UTC)


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def make(tmp_path, start):
    ex = FakeEx(price=2000.0, usdc=96.0)
    clock = Clock(start)
    bot = make_grid(tmp_path, ex)
    bot.now = clock
    return ex, bot, clock


def test_weekly_report_sent_once_and_csv_daily(tmp_path):
    ex, bot, clock = make(tmp_path, datetime(2025, 11, 12, 10, tzinfo=UTC))  # srijeda
    bot.check_once()
    assert bot.state.report["start_value"] == 96.0
    assert not any("Tjedni izvještaj" in m for m in bot.tg.sent)

    # isti dan ponovno -> nema novog retka ni izvještaja
    bot.check_once()
    csv_path = tmp_path / "povijest.csv"
    assert len(csv_path.read_text().strip().splitlines()) == 2  # zaglavlje + 1 dan

    # cijeli krug: kupnja pa prodaja
    lv = bot.g["levels"]
    ex.fill("BUY", lambda p: abs(p - lv[3]) < 1e-6)
    clock.t += timedelta(hours=1)
    bot.check_once()
    ex.fill("SELL", lambda p: True)
    bot.check_once()
    assert bot.state.report["cycles_total"] == 1

    # nedjelja 20h UTC -> izvještaj
    clock.t = datetime(2025, 11, 16, 20, tzinfo=UTC)
    bot.check_once()
    reports = [m for m in bot.tg.sent if "Tjedni izvještaj" in m]
    assert len(reports) == 1
    assert "krugova: 1" in reports[0] and "samo kupi i drži" in reports[0]
    bot.check_once()
    assert len([m for m in bot.tg.sent if "Tjedni izvještaj" in m]) == 1
    assert len(csv_path.read_text().strip().splitlines()) == 3  # zaglavlje + srijeda + nedjelja


def test_missed_report_sent_when_bot_comes_back(tmp_path):
    ex, bot, clock = make(tmp_path, datetime(2025, 11, 12, 10, tzinfo=UTC))
    bot.check_once()
    clock.t = datetime(2025, 11, 18, 9, tzinfo=UTC)  # računalo bilo ugašeno u nedjelju
    bot.check_once()
    assert any("Tjedni izvještaj" in m for m in bot.tg.sent)


def test_totals_survive_close_all(tmp_path):
    ex, bot, clock = make(tmp_path, datetime(2025, 11, 12, 10, tzinfo=UTC))
    bot.check_once()
    lv = bot.g["levels"]
    ex.fill("BUY", lambda p: abs(p - lv[3]) < 1e-6)
    bot.check_once()
    ex.fill("SELL", lambda p: True)
    bot.check_once()
    bot.close_all()
    assert bot.g == {} and bot.state.report["cycles_total"] == 1


def test_izvjestaj_command(tmp_path):
    ex, bot, clock = make(tmp_path, datetime(2025, 11, 12, 10, tzinfo=UTC))
    bot.check_once()
    bot.tg.poll_commands = lambda: ["/izvjestaj"]
    bot.handle_commands()
    assert "Od početka" in bot.tg.sent[-1]
