"""v4 washout bot: entry from drawdown vs a rolling high (not vs a moving average).

Why a different architecture: v3's dip-vs-SMA-90 never fires in a falling
window because the SMA itself falls with the price, and the SMA not-falling
filters block the deeper dips. A rolling HIGH is a fixed anchor: it does not
fall with the price, so a -2% drawdown from the high DOES fire in a falling
knife, and the reversal confirmation keeps us from catching it mid-fall.

Design (principled, not overfit):
  - Reference: rolling high = max close over the last high_n bars.
  - Entry: close is dd_bps below the rolling high AND a reversal
    confirmation (upbar / two_up). Max ONE trade per 24h (no re-entry).
  - Exit: TP tp_bps over cost, trailing stop trail_bps from peak value,
    hard SL sl_bps under cost, flatten at the last close.
  - Size: size_bps of cash (<= 6000 = 60%).
"""
from collections import deque
from backtest import bars_value, BPS


def make_washout(p):
    high_n = p.get('high_n', 240)
    dd = p.get('dd_bps', 200)
    confirm = p.get('confirm', 'two_up')
    tp = p.get('tp_bps', 180)
    sl = p.get('sl_bps', 200)
    trail = p.get('trail_bps', 110)
    size = p.get('size_bps', 6000)
    max_trades = p.get('max_trades', 1)
    state = {'peak_value': 0, 'trades_done': 0, 'dq': deque(), 'last_i': -1}

    def decide(i, closes, cash, qty, cost, bars):
        # Maintain a monotonic deque for the sliding-window max of closes.
        dq = state['dq']
        if i != state['last_i']:
            # new bar: push closes[i], drop indices outside the window
            while dq and closes[dq[-1]] <= closes[i]:
                dq.pop()
            dq.append(i)
            while dq and dq[0] < i - high_n + 1:
                dq.popleft()
            state['last_i'] = i
        if qty == 0:
            state['peak_value'] = 0
            if state['trades_done'] >= max_trades:
                return None
            if i + 1 < high_n + 2:
                return None
            high = closes[dq[0]]
            close = closes[i]
            # drawdown: close * BPS <= high * (BPS - dd)
            if close * BPS > high * (BPS - dd):
                return None
            # reversal confirmation: do not catch the knife mid-fall
            if confirm == 'upbar' and close <= closes[i - 1]:
                return None
            if confirm == 'two_up' and (close <= closes[i - 1] or closes[i - 1] <= closes[i - 2]):
                return None
            if confirm == 'three_up' and (close <= closes[i - 1] or closes[i - 1] <= closes[i - 2]
                                          or closes[i - 2] <= closes[i - 3]):
                return None
            state['trades_done'] += 1
            return ('buy', cash * size // BPS)
        value = bars_value(qty, closes[i])
        if value > state['peak_value']:
            state['peak_value'] = value
        if value * BPS >= cost * (BPS + tp):
            return ('sell', qty)
        if trail and state['peak_value'] > 0 and value * BPS <= state['peak_value'] * (BPS - trail):
            return ('sell', qty)
        if value * BPS <= cost * (BPS - sl):
            return ('sell', qty)
        return None

    return decide


def fmt(r):
    wr = r['win_rate']
    wr_s = f"{wr:.0%}" if wr is not None else "-"
    return (f"PnL ${r['pnl_usd']:+7.2f} tr={r['trades']} rt={r['roundtrips']} "
            f"win={wr_s} maxDD={r['max_dd_pct']:.2f}% fees=${r['fees_usd']:.2f}")
