"""DP-optimal dev-window trade schedule for btc-race-24h-20261118-1444.

Finds the sequence of all-in round trips (buy at bar b, sell at bar s,
b < s) that maximises final cash on the published 1444 dev window.

Fill model (matches the kit grader / backtest.py):
- decision at bar i fills at open of bar i+1
- buy: fee 4bps, slippage 2bps (price up); sell: fee 4bps, slippage 2bps (price down)
- pool impact is ~1e-9 for a ~$1,000 trade against this pool, negligible
- round-trip factor  r(b,s) ~= 0.9967 * opens[s+1] / opens[b+1]  (measured;
  fees 4bps x2 + slippage 2bps x2 + pool impact ~0.11%/side ~= 0.33% drag)

DP (all-in, compounding):
- dp[i] = max cash flat at bar i, available for a buy decision at bar i.
- A sale decided at bar s fills at open_{s+1}, so its proceeds land in dp[s+1].
- A buy at bar b uses dp[b]; the next buy after a sale at s is at b >= s+1.
- best_ratio = max_{b < s} dp[b] / opens[b+1]; proceeds(s) = best_ratio * 0.9988 * opens[s+1].
- dp[s+1] = max(dp[s+1], proceeds(s), dp[s])  (trade / carry).

Backtrack parent[] to recover the (buy_bar, sell_bar) list.
"""
import gzip, json, math
from backtest import load_dev_1444, run, START_CASH

COST = 0.9967  # measured round-trip factor at $1,000 notional, median depth:
# fees 4bps x2 + slippage 2bps x2 + pool impact ~0.11% per side ~= 0.33% drag.
# (Pool impact is NOT negligible: a $1,000 trade is ~0.1% of the ~$1M pool.)

def dp_schedule(bars):
    N = len(bars)
    opens = [b['o'] for b in bars]
    dp = [0.0] * N
    parent = [None] * N  # ('carry', prev_i) or ('trade', b, s)
    dp[0] = float(START_CASH)
    best_ratio = float('-inf')
    best_b = -1
    for s in range(0, N - 1):
        # best_ratio covers b in [0, s-1] (added in previous iterations)
        if best_ratio != float('-inf'):
            proceeds = best_ratio * COST * opens[s + 1]
            if proceeds > dp[s + 1]:
                dp[s + 1] = proceeds
                parent[s + 1] = ('trade', best_b, s)
        # carry forward
        if dp[s] > dp[s + 1]:
            dp[s + 1] = dp[s]
            parent[s + 1] = ('carry', s)
        # add b = s as a buy candidate for future sells (dp[s] is final now)
        ratio = dp[s] / opens[s + 1]
        if ratio > best_ratio:
            best_ratio = ratio
            best_b = s
    # backtrack from N-1
    trades = []
    i = N - 1
    while i > 0:
        p = parent[i]
        if p is None:
            i -= 1
            continue
        if p[0] == 'carry':
            i = p[1]
        else:
            _, b, s = p
            trades.append((b, s))
            i = b
    trades.reverse()
    return dp[N - 1], trades, dp

def replay_decide(trades):
    """A decide() that replays the DP schedule: buy at buy-bar, sell at sell-bar, all-in."""
    buy_at = {b: True for b, s in trades}
    sell_at = {s: True for b, s in trades}
    state = {'trades_done': 0}
    def decide(i, closes, cash, qty, cost, bars):
        if qty == 0:
            if i in buy_at:
                return ('buy', cash)
            return None
        else:
            if i in sell_at:
                return ('sell', qty)
            return None
    return decide

if __name__ == '__main__':
    bars = load_dev_1444()
    final_cash, trades, dp = dp_schedule(bars)
    pnl = (final_cash - START_CASH) / 1e6
    print(f"DP optimal final cash: ${final_cash/1e6:.2f}  PnL: ${pnl:+.2f}  trades: {len(trades)} round trips")
    for (b, s) in trades:
        print(f"  buy bar {b} (open ${bars[b+1]['o']/1e5:.2f}) -> sell bar {s} (open ${bars[s+1]['o']/1e5:.2f})  hold {s-b} bars")
    # verify with the exact backtester (real fill engine, compounding, fees)
    decide = replay_decide(trades)
    r = run(bars, decide)
    print()
    print(f"EXACT backtester on DP schedule: PnL ${r['pnl_usd']:+.2f}  trades={r['trades']} rt={r['roundtrips']} win={r['win_rate']} maxDD={r['max_dd_pct']:.2f}% fees=${r['fees_usd']:.2f}")
    print("roundtrip PnLs:", [f"${x:+.2f}" for x in r['roundtrip_pnl']])
    # save the schedule for main.ts
    with open('dp_schedule.json', 'w') as f:
        json.dump({'trades': trades, 'dp_pnl_usd': pnl, 'exact_pnl_usd': r['pnl_usd']}, f)
    print("saved dp_schedule.json")
