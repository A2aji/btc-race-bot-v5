"""Parametrized dip-buying strategies in integer math, mirroring main.ts logic."""
from backtest import bars_value, BPS

def sma(closes, n, end_i):
    return sum(closes[end_i - n + 1:end_i + 1])

def make_old():
    """Old bot: SMA90 dip 55bps, regime SMA90 not falling, TP 140, SL 100, all-in."""
    def decide(i, closes, cash, qty, cost, bars):
        if qty == 0:
            if i + 1 < 92: return None
            total = sma(closes, 90, i)
            close = closes[i]
            if close * 90 * BPS >= total * (BPS - 55): return None
            old = closes[i - 91]
            if total * BPS < old * (BPS - 10) * 90: return None
            return ('buy', cash)
        else:
            value = bars_value(qty, closes[i])
            if value * BPS >= cost * (BPS + 140): return ('sell', qty)
            if value * BPS <= cost * (BPS - 100): return ('sell', qty)
            return None
    return decide

def make_new(p):
    """New bot. p keys:
    slow=90, dip_bps, tp_bps, sl_bps, trail_bps (0=off), long_n=200,
    long_filter: 'none'|'above'|'rising'|'both', confirm: 'none'|'upbar'|'above_half',
    size_bps (10000=all-in), cooldown_bars (after SL), min_hold_bars."""
    slow = p.get('slow', 90); dip = p.get('dip_bps', 70); tp = p.get('tp_bps', 200)
    sl = p.get('sl_bps', 150); trail = p.get('trail_bps', 120)
    long_n = p.get('long_n', 200); lf = p.get('long_filter', 'both')
    confirm = p.get('confirm', 'upbar'); size = p.get('size_bps', 6000)
    cooldown = p.get('cooldown_bars', 120)
    state = {'peak_value': 0, 'last_sl_i': -10**9, 'entry_i': -1}
    def decide(i, closes, cash, qty, cost, bars):
        if qty == 0:
            if i + 1 < max(slow + 2, long_n + 1): return None
            if i - state['last_sl_i'] < cooldown: return None
            total = sma(closes, slow, i)
            close = closes[i]
            if close * slow * BPS >= total * (BPS - dip): return None
            # regime: slow avg not falling
            old = closes[i - slow - 1]
            if total * BPS < old * (BPS - 10) * slow: return None
            # long filter
            if lf in ('above', 'both'):
                ltot = sma(closes, long_n, i)
                if close * long_n < ltot: return None  # close below SMA200
            if lf in ('rising', 'both'):
                ltot = sma(closes, long_n, i)
                lold = closes[i - long_n]
                # SMA200 not falling: avg >= close 201 bars ago (within 0.1%)
                if ltot * BPS < lold * (BPS - 10) * long_n: return None
            # confirmation
            if confirm == 'upbar' and closes[i] <= closes[i - 1]: return None
            if confirm == 'above_half':
                # close back above avg - dip/2
                if close * slow * BPS < total * (BPS - dip // 2): return None
            notional = cash * size // BPS
            return ('buy', notional)
        else:
            value = bars_value(qty, closes[i])
            if value > state['peak_value']: state['peak_value'] = value
            if value * BPS >= cost * (BPS + tp): return ('sell', qty)
            if trail and state['peak_value'] > 0:
                if value * BPS <= state['peak_value'] * (BPS - trail):
                    state['last_sl_i'] = i; state['peak_value'] = 0
                    return ('sell', qty)
            if value * BPS <= cost * (BPS - sl):
                state['last_sl_i'] = i; state['peak_value'] = 0
                return ('sell', qty)
            return None
    # reset peak on new buy: wrap decide to detect transitions
    orig = decide
    def wrapped(i, closes, cash, qty, cost, bars):
        if qty == 0: state['peak_value'] = 0
        return orig(i, closes, cash, qty, cost, bars)
    return wrapped

def make_new2(p):
    """v2: adds max_hold_bars and regime_exit (sell when slow avg turns falling)."""
    slow = p.get('slow', 90); dip = p.get('dip_bps', 45); tp = p.get('tp_bps', 140)
    sl = p.get('sl_bps', 200); trail = p.get('trail_bps', 100)
    long_n = p.get('long_n', 200); lf = p.get('long_filter', 'rising')
    tol = p.get('long_tol_bps', 10)
    confirm = p.get('confirm', 'none'); size = p.get('size_bps', 6000)
    cooldown = p.get('cooldown_bars', 0); max_hold = p.get('max_hold_bars', 0)
    regime_exit = p.get('regime_exit', False)
    state = {'peak_value': 0, 'last_sl_i': -10**9, 'entry_i': -1, 'entry_cost': 0}
    def decide(i, closes, cash, qty, cost, bars):
        if qty == 0:
            state['peak_value'] = 0
            if i + 1 < max(slow + 2, long_n + 1): return None
            if i - state['last_sl_i'] < cooldown: return None
            total = sma(closes, slow, i)
            close = closes[i]
            if close * slow * BPS >= total * (BPS - dip): return None
            old = closes[i - slow - 1]
            if total * BPS < old * (BPS - 10) * slow: return None
            if lf == 'rising':
                ltot = sma(closes, long_n, i)
                lold = closes[i - long_n]
                if ltot * BPS < lold * (BPS - tol) * long_n: return None
            elif lf == 'rising120':
                ltot = sma(closes, 120, i)
                lold = closes[i - 121]
                if ltot * BPS < lold * (BPS - tol) * 120: return None
            if confirm == 'upbar' and closes[i] <= closes[i - 1]: return None
            state['entry_i'] = i
            return ('buy', cash * size // BPS)
        value = bars_value(qty, closes[i])
        if value > state['peak_value']: state['peak_value'] = value
        if value * BPS >= cost * (BPS + tp): return ('sell', qty)
        if trail and state['peak_value'] > 0 and value * BPS <= state['peak_value'] * (BPS - trail):
            state['last_sl_i'] = i; return ('sell', qty)
        if value * BPS <= cost * (BPS - sl):
            state['last_sl_i'] = i; return ('sell', qty)
        if regime_exit:
            total = sma(closes, slow, i)
            old = closes[i - slow - 1]
            if total * BPS < old * (BPS - 10) * slow:
                state['last_sl_i'] = i; return ('sell', qty)
        if max_hold and i - state['entry_i'] >= max_hold:
            return ('sell', qty)
        return None
    return decide

def make_new3(p):
    """v3: MAD-normalized dip entry and/or bounce entry; exit to mean optional.
    entry: 'dip' (fixed bps vs SMA) | 'mad' ((avg-close) >= k * MAD90, k in 1/10 units)
           | 'bounce' (dip within last K bars AND close > SMA30 and rising)
    exit_mode: 'std' (TP/SL/trail) | 'mean' (sell at/above SMA slow) | 'std_or_mean'
    """
    slow = p.get('slow', 90); dip = p.get('dip_bps', 45)
    tp = p.get('tp_bps', 140); sl = p.get('sl_bps', 200); trail = p.get('trail_bps', 100)
    lf = p.get('long_filter', 'rising'); tol = p.get('long_tol_bps', 10)
    confirm = p.get('confirm', 'none'); size = p.get('size_bps', 6000)
    entry = p.get('entry', 'dip'); mad_k10 = p.get('mad_k10', 12)  # 1.2x MAD
    exit_mode = p.get('exit_mode', 'std'); bounce_k = p.get('bounce_k', 60)
    state = {'peak_value': 0, 'last_sl_i': -10**9, 'entry_i': -1}
    def _sma(closes, i, n):
        return sum(closes[i-n+1:i+1])
    def decide(i, closes, cash, qty, cost, bars):
        if qty == 0:
            state['peak_value'] = 0
            if i + 1 < max(slow + 2, 201): return None
            total = _sma(closes, i, slow); close = closes[i]
            avg = total // slow
            # regime: slow avg not falling
            old = closes[i - slow - 1]
            if total * BPS < old * (BPS - 10) * slow: return None
            if lf == 'rising':
                ltot = _sma(closes, i, 200); lold = closes[i - 200]
                if ltot * BPS < lold * (BPS - tol) * 200: return None
            if entry == 'dip':
                if close * slow * BPS >= total * (BPS - dip): return None
            elif entry == 'mad':
                mad = sum(abs(c - avg) for c in closes[i-slow+1:i+1]) // slow
                if (avg - close) * 10 < mad * mad_k10: return None
            elif entry == 'bounce':
                # dip vs slow within last bounce_k bars, and close above SMA30 + up bar
                s30 = _sma(closes, i, 30)
                if close * 30 <= s30: return None
                if closes[i] <= closes[i-1]: return None
                found = False
                for j in range(max(slow+1, i-bounce_k), i+1):
                    tj = _sma(closes, j, slow)
                    if closes[j] * slow * BPS < tj * (BPS - dip): found = True; break
                if not found: return None
            if confirm == 'upbar' and closes[i] <= closes[i - 1]: return None
            state['entry_i'] = i
            return ('buy', cash * size // BPS)
        value = bars_value(qty, closes[i])
        if value > state['peak_value']: state['peak_value'] = value
        if exit_mode in ('mean', 'std_or_mean'):
            total = _sma(closes, i, slow)
            if closes[i] * slow >= total:  # back at/above mean
                return ('sell', qty)
        if exit_mode in ('std', 'std_or_mean'):
            if value * BPS >= cost * (BPS + tp): return ('sell', qty)
            if trail and state['peak_value'] > 0 and value * BPS <= state['peak_value'] * (BPS - trail):
                state['last_sl_i'] = i; return ('sell', qty)
            if value * BPS <= cost * (BPS - sl):
                state['last_sl_i'] = i; return ('sell', qty)
        return None
    return decide

def make_scalp(p):
    """High-frequency small-size mean-reversion scalp.
    fast=n-bar SMA; entry close < SMA*(1-dip); exit TP/SL/trail or back-to-mean.
    size_bps of cash per trade (small size => tiny price impact)."""
    n = p.get('fast', 20); dip = p.get('dip_bps', 20)
    tp = p.get('tp_bps', 60); sl = p.get('sl_bps', 120); trail = p.get('trail_bps', 0)
    size = p.get('size_bps', 2000); cooldown = p.get('cooldown_bars', 0)
    regime = p.get('regime', 'none')  # none | slow90 (SMA90 not falling) | slow200rising
    confirm = p.get('confirm', 'none')
    exit_mean = p.get('exit_mean', False)
    state = {'peak_value': 0, 'last_exit_i': -10**9}
    def decide(i, closes, cash, qty, cost, bars):
        if qty == 0:
            state['peak_value'] = 0
            if i + 1 < n + 1: return None
            if i - state['last_exit_i'] < cooldown: return None
            total = sum(closes[i-n+1:i+1]); close = closes[i]
            if close * n * BPS >= total * (BPS - dip): return None
            if regime == 'slow90':
                if i + 1 < 92: return None
                t90 = sum(closes[i-89:i+1]); old = closes[i-91]
                if t90 * BPS < old * (BPS - 10) * 90: return None
            if regime == 'slow200rising':
                if i + 1 < 201: return None
                t200 = sum(closes[i-199:i+1]); lold = closes[i-200]
                if t200 * BPS < lold * (BPS - 10) * 200: return None
            if confirm == 'upbar' and closes[i] <= closes[i-1]: return None
            return ('buy', cash * size // BPS)
        value = bars_value(qty, closes[i])
        if value > state['peak_value']: state['peak_value'] = value
        if exit_mean:
            total = sum(closes[i-n+1:i+1])
            if closes[i] * n >= total:
                state['last_exit_i'] = i; return ('sell', qty)
        if value * BPS >= cost * (BPS + tp):
            state['last_exit_i'] = i; return ('sell', qty)
        if trail and state['peak_value'] > 0 and value * BPS <= state['peak_value'] * (BPS - trail):
            state['last_exit_i'] = i; return ('sell', qty)
        if value * BPS <= cost * (BPS - sl):
            state['last_exit_i'] = i; return ('sell', qty)
        return None
    return decide

def make_new4(p):
    """v4 = B5t110 + confirm variants + optional small-size shallow-dip fallback mode.
    confirm: 'upbar' | 'green' | 'upbar_green' | 'two_up'
    fallback: if no trade yet and i>=fb_after, allow dip_fb vs slow with size_fb, tp_fb/sl_fb/trl_fb."""
    slow = p.get('slow', 90); dip = p.get('dip_bps', 70); tp = p.get('tp_bps', 140)
    sl = p.get('sl_bps', 200); trail = p.get('trail_bps', 110)
    size = p.get('size_bps', 6000); confirm = p.get('confirm', 'upbar')
    fb = p.get('fallback', None)
    state = {'peak_value': 0, 'entry_i': -1, 'traded': False, 'fb_mode': False}
    def decide(i, closes, cash, qty, cost, bars):
        if qty == 0:
            state['peak_value'] = 0
            if i + 1 < 202: return None
            total = sma(closes, slow, i); close = closes[i]
            # long filter: SMA200 not falling
            ltot = sma(closes, 200, i); lold = closes[i - 200]
            if ltot * BPS < lold * (BPS - 10) * 200: return None
            # regime: slow avg not falling
            old = closes[i - slow - 1]
            if total * BPS < old * (BPS - 10) * slow: return None
            d = dip; sz = size
            use_fb = False
            if close * slow * BPS >= total * (BPS - d):
                if fb and not state['traded'] and i >= fb['after']:
                    d = fb['dip_bps']; sz = fb['size_bps']
                    if close * slow * BPS >= total * (BPS - d): return None
                    use_fb = True
                else:
                    return None
            # confirmation
            if confirm == 'upbar' and closes[i] <= closes[i-1]: return None
            if confirm == 'green' and closes[i] <= bars[i]['o']: return None
            if confirm == 'upbar_green' and (closes[i] <= closes[i-1] or closes[i] <= bars[i]['o']): return None
            if confirm == 'two_up' and (closes[i] <= closes[i-1] or closes[i-1] <= closes[i-2]): return None
            if confirm == 'three_up' and (closes[i] <= closes[i-1] or closes[i-1] <= closes[i-2] or closes[i-2] <= closes[i-3]): return None
            state['entry_i'] = i; state['fb_mode'] = use_fb; state['traded'] = True
            return ('buy', cash * sz // BPS)
        value = bars_value(qty, closes[i])
        if value > state['peak_value']: state['peak_value'] = value
        t = tp; s = sl; tr = trail
        if state['fb_mode'] and fb:
            t = fb['tp_bps']; s = fb['sl_bps']; tr = fb['trail_bps']
        if value * BPS >= cost * (BPS + t): return ('sell', qty)
        if tr and state['peak_value'] > 0 and value * BPS <= state['peak_value'] * (BPS - tr):
            return ('sell', qty)
        if value * BPS <= cost * (BPS - s): return ('sell', qty)
        return None
    return decide
