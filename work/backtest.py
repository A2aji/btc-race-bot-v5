"""Independent backtester replicating the make.fun bars-replay/v1 fill engine
in exact integer arithmetic (see harness sim/bars/engine.ts: BarsPool,
barsBuyFill, barsSellFill, barsValue). Fee 4bps, slippage 2bps, impact via
constant-product pool of the bar's open depth. Fills at next bar's open.
Flatten at last close vs c_depth. No warmup (grade-local hello has none;
validated by reproducing the old bot's dev PnL exactly)."""
import gzip, json, math
from fractions import Fraction

BPS = 10_000
FEE_BPS = 4
SLIP_BPS = 2
START_CASH = 1_000_000_000  # quote units ($1000, quote_scale 6)
MIN_NOTIONAL = 1_000_000
MED_DEPTH = 880_211_041_956  # median dev o_depth (raw units), used for Coinbase windows

def bars_value(q, p):
    return (q * p * 10**6) // 10**(8 + 5)

class Pool:
    """Single-hop BarsPool. D = depth*10^6 (quote_scale 6). y kept as fraction yn/yd."""
    def __init__(self, depth_raw):
        d = depth_raw * 10**6
        self.yn, self.yd = d, 1
        self.kn, self.kd = d * d, 1
        self.unit = 10**6
    def buy_factor(self, spend):
        yn2 = self.yn + spend * self.unit * self.yd
        num = self.yn * yn2 * self.kd
        den = self.yd * self.yd * self.kn
        after = Pool.__new__(Pool)
        after.yn, after.yd, after.kn, after.kd, after.unit = yn2, self.yd, self.kn, self.kd, self.unit
        return num, den, after
    def sell_factor(self, value):
        t = self.kn * self.yd + value * self.unit * self.yn * self.kd
        num = t * self.yd
        den = self.kd * self.yn * self.yn
        after = Pool.__new__(Pool)
        after.yn, after.yd, after.kn, after.kd, after.unit = self.kn * self.yn, t, self.kn, self.kd, self.unit
        return num, den, after

def buy_fill(notional, open_p, depth_raw):
    spend = (notional * (BPS - FEE_BPS)) // BPS
    pool = Pool(depth_raw)
    num, den, _ = pool.buy_factor(spend)
    price = (open_p * (BPS + SLIP_BPS) * num) // (BPS * den)
    qty = (spend * 10**(8 + 5)) // (price * 10**6)
    return price, spend, notional - spend, qty

def sell_fill(qty, open_p, depth_raw):
    pool = Pool(depth_raw)
    v = bars_value(qty, open_p)
    num, den, _ = pool.sell_factor(v)
    slipped = (open_p * (BPS - SLIP_BPS) * den) // (BPS * num)
    price = max(1, slipped)
    gross = bars_value(qty, price)
    proceeds = (gross * (BPS - FEE_BPS)) // BPS
    return price, gross, gross - proceeds, proceeds

def load_dev_kit(path):
    rows = [json.loads(l) for l in gzip.open(path, 'rt')]
    return [{'t': r['t'], 'o': int(r['o']), 'h': int(r['h']), 'l': int(r['l']),
             'c': int(r['c']), 'od': int(r['o_depth'][0]), 'cd': int(r['c_depth'][0])} for r in rows]

def load_dev():
    return load_dev_kit(
        '/home/hatch/workspace/makefun/btc-race-24h-20261117-0603-kit/btc-race-24h-20261117-0603-kit/dataset/bars/CBBTC.ndjson.gz')

def load_dev_1444():
    return load_dev_kit(
        '/home/hatch/workspace/makefun/btc-race-24h-20261118-1444-kit/btc-race-24h-20261118-1444-kit/dataset/bars/CBBTC.ndjson.gz')

def load_live_partial():
    """Race window 2026-11-17 12:18 UTC -> as far as recorded (~02:29 UTC Nov 18, ~611 bars).
    The actual live window that killed the old bot; partial because the race is still running."""
    import datetime
    candles = json.load(open('btc_1m_live.json'))
    by = {c[0]: c for c in candles}
    s_ts = int(datetime.datetime(2026, 11, 17, 12, 18, tzinfo=datetime.timezone.utc).timestamp())
    bars = []
    prev_c = None
    i = 0
    while True:
        t = s_ts + i * 60
        if t not in by:
            break
        c = by[t]
        o, h, l, cl = c[3], c[2], c[1], c[4]
        bars.append({'t': t * 1000, 'o': int(round(o * 1e5)), 'h': int(round(h * 1e5)),
                     'l': int(round(l * 1e5)), 'c': int(round(cl * 1e5)),
                     'od': MED_DEPTH, 'cd': MED_DEPTH})
        prev_c = cl
        i += 1
    return bars

def load_coinbase(day_start_ts):
    """1440 1m bars starting at day_start_ts (unix s, 06:00 UTC). Missing minute -> flat bar at prev close."""
    import datetime
    candles = json.load(open('btc_1m_coinbase.json'))
    by = {c[0]: c for c in candles}
    bars = []
    prev_c = None
    for i in range(1440):
        t = day_start_ts + i * 60
        if t in by:
            c = by[t]  # [time, low, high, open, close, volume]
            o, h, l, cl = c[3], c[2], c[1], c[4]
            prev_c = cl
        else:
            o = h = l = cl = prev_c
        # price_scale 5: raw = USD * 1e5
        bars.append({'t': t * 1000, 'o': int(round(o * 1e5)), 'h': int(round(h * 1e5)),
                     'l': int(round(l * 1e5)), 'c': int(round(cl * 1e5)),
                     'od': MED_DEPTH, 'cd': MED_DEPTH})
    return bars

WINDOWS = {}
def get_windows():
    if WINDOWS: return WINDOWS
    import datetime
    def ts(y, m, d):
        return int(datetime.datetime(y, m, d, 6, 0, tzinfo=datetime.timezone.utc).timestamp())
    WINDOWS['D1444-dev'] = load_dev_1444()
    WINDOWS['D0603-dev'] = load_dev()
    WINDOWS['W0-dev'] = load_dev()
    WINDOWS['W1-down-mild'] = load_coinbase(ts(2026, 11, 8))    # -1.76%
    WINDOWS['W2-crash'] = load_coinbase(ts(2026, 11, 12))       # -7.44%
    WINDOWS['W3-down-vol'] = load_coinbase(ts(2026, 11, 14))   # -4.08%
    WINDOWS['W4-sideways'] = load_coinbase(ts(2026, 11, 9))    # +0.45%
    WINDOWS['W5-flat'] = load_coinbase(ts(2026, 11, 7))        # -0.27%
    WINDOWS['W6-down-mild2'] = load_coinbase(ts(2026, 11, 10)) # -1.13%
    WINDOWS['W7-down-mild3'] = load_coinbase(ts(2026, 11, 11)) # -0.47%
    WINDOWS['W8-down-mild4'] = load_coinbase(ts(2026, 11, 13)) # ~-1.2% (1 flat-filled min)
    WINDOWS['W9-down-mild5'] = load_coinbase(ts(2026, 11, 15)) # ~-0.3%? (1 flat-filled min)
    WINDOWS['W10-live-partial'] = load_live_partial()  # race window, ~611 bars, 2x vol
    return WINDOWS

def run(bars, decide, max_slip_bps=100):
    """decide(i, closes, cash, qty, cost) -> ('buy', notional) | ('sell', qty) | None.
    Decision at bar i fills at open of bar i+1. Returns dict of metrics + trade log."""
    closes = [b['c'] for b in bars]
    cash = START_CASH
    qty = 0
    cost = 0
    trades = []      # (bar_i, side, price, qty/notional, fee)
    roundtrips = []  # completed sell PnL vs cost
    equity_curve = []
    peak = START_CASH
    max_dd = 0.0
    pending = None  # (kind, amount, decided_close, decided_i)
    fees = 0
    n_buys = 0
    for i, b in enumerate(bars):
        # resolve pending order at this bar's open
        if pending is not None:
            kind, amt, dec_close, dec_i = pending
            pending = None
            if i == len(bars) - 1 and False:
                pass
            if kind == 'buy':
                price, spend, fee, q = buy_fill(amt, b['o'], b['od'])
                # max slippage vs decided close
                if price * BPS > dec_close * (BPS + max_slip_bps):
                    pass  # rejected
                elif amt < MIN_NOTIONAL:
                    pass
                else:
                    cash -= amt
                    qty += q
                    cost += amt  # cost = notional spent (incl fee), matches engine cost bookkeeping approx
                    fees += fee
                    n_buys += 1
                    trades.append((dec_i, 'buy', price, q, fee))
            else:
                price, gross, fee, proceeds = sell_fill(amt, b['o'], b['od'])
                if price * BPS < dec_close * (BPS - max_slip_bps):
                    pass
                else:
                    cash += proceeds
                    fees += fee
                    trades.append((dec_i, 'sell', price, amt, fee))
                    if qty == amt:
                        roundtrips.append(proceeds - cost)
                        qty = 0; cost = 0
                    else:
                        # partial sell: scale cost
                        cost = cost * (qty - amt) // qty if qty else 0
                        qty -= amt
        # equity at this bar's close
        eq = cash + (bars_value(qty, b['c']) if qty else 0)
        equity_curve.append(eq)
        if eq > peak: peak = eq
        dd = (peak - eq) / peak
        if dd > max_dd: max_dd = dd
        # decide (not on last bar: after_end)
        if i >= len(bars) - 1:
            continue
        action = decide(i, closes, cash, qty, cost, bars)
        if action is None:
            continue
        if action[0] == 'buy' and qty == 0:
            notional = min(action[1], cash)
            if notional >= MIN_NOTIONAL:
                pending = ('buy', notional, b['c'], i)
        elif action[0] == 'sell' and qty > 0:
            q = min(action[1], qty)
            if bars_value(q, b['c']) >= MIN_NOTIONAL or q == qty:
                pending = ('sell', q, b['c'], i)
    # flatten at last close vs c_depth
    if qty > 0:
        price, gross, fee, proceeds = sell_fill(qty, bars[-1]['c'], bars[-1]['cd'])
        cash += proceeds
        fees += fee
        trades.append((len(bars) - 1, 'flatten', price, qty, fee))
        roundtrips.append(proceeds - cost)
        qty = 0
    pnl = cash - START_CASH
    wins = sum(1 for r in roundtrips if r > 0)
    return {'pnl_usd': pnl / 1e6, 'pnl_units': pnl, 'trades': len([t for t in trades if t[1] in ('buy', 'sell')]),
            'fills': len(trades), 'fees_usd': fees / 1e6, 'max_dd_pct': max_dd * 100,
            'roundtrips': len(roundtrips), 'wins': wins,
            'win_rate': (wins / len(roundtrips) if roundtrips else None),
            'final_cash_usd': cash / 1e6, 'trade_log': trades, 'roundtrip_pnl': [r / 1e6 for r in roundtrips]}
