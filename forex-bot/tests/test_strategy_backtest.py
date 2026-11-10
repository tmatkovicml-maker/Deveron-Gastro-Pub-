from forexbot.backtest import load_csv, run_backtest, save_csv
from forexbot.strategy import StrategyParams, compute_indicators, generate_signal, signal_at


def test_no_signal_with_too_few_candles(wave_candles):
    assert generate_signal(wave_candles[:100], StrategyParams()) is None


def test_signals_follow_rules(wave_candles):
    p = StrategyParams()
    ind = compute_indicators(wave_candles, p)
    sigs = [(i, signal_at(wave_candles, ind, i, p)) for i in range(len(wave_candles))]
    sigs = [(i, s) for i, s in sigs if s]
    assert sigs, "očekivani su signali na valovitim podacima"
    for i, s in sigs:
        assert s.sl_distance > 0 and s.tp_distance == 2 * s.sl_distance
        if s.side == "buy":
            assert ind["fast"][i] > ind["slow"][i] and wave_candles[i].close > ind["trend"][i]
        else:
            assert ind["fast"][i] < ind["slow"][i] and wave_candles[i].close < ind["trend"][i]


def test_generate_signal_matches_signal_at(wave_candles):
    p = StrategyParams()
    ind = compute_indicators(wave_candles, p)
    for i in range(p.min_candles(), len(wave_candles), 7):
        a = generate_signal(wave_candles[: i + 1], p)
        b = signal_at(wave_candles, ind, i, p)
        assert (a is None) == (b is None)


def test_backtest_runs_and_accounts(wave_candles):
    res = run_backtest(wave_candles, StrategyParams(), instrument="EUR_USD", start_balance=500)
    assert res.trades
    assert abs(res.start_balance + sum(t.pnl for t in res.trades) - res.end_balance) < 1e-6
    assert 0 <= res.max_drawdown < 1
    for t in res.trades:
        assert t.result in ("SL", "TP")
        assert t.exit_time >= t.entry_time
    assert "Backtest EUR_USD" in res.summary()


def test_csv_roundtrip(tmp_path, wave_candles):
    path = tmp_path / "c.csv"
    save_csv(wave_candles[:10], path)
    loaded = load_csv(path)
    assert [c.close for c in loaded] == [c.close for c in wave_candles[:10]]
