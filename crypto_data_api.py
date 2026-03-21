"""
crypto_data_api.py
==================
市场交易项目 - 标准化 Crypto 数据接口模块
任何 Agent 均可直接导入或运行此模块以获取实时数据。
数据源：CoinGecko API（免费，无需 API Key）

数据体系说明：
  T0 - 原始标的池：从 CoinGecko 市值前 300 中，剔除稳定币和模因币（保留 DOGE），
       取前 150 名作为候选池。
  T1 - 每周观察表：从 T0 中按总市值排序，取前 50 名作为本周核心观察标的。
  T2 - 实时 K 线：T1 中各标的的多周期 OHLC 数据，以纽约时间 08:00 为锚点对齐。
       - 15min 周期：过去 2 天（CoinGecko 免费版最小粒度约 30min，建议用 1h 替代）
       - 1h 周期：过去 7 天
       - 4h 周期：过去 30 天（CoinGecko 返回 4h 粒度）
       - 1D 周期：过去 90 天

时区基准：所有时间逻辑以纽约时间（America/New_York）为准。

安装依赖：pip3 install requests pandas pytz
"""

import requests
import pandas as pd
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

try:
    import pytz
except ImportError:
    import subprocess
    subprocess.run(['pip3', 'install', 'pytz', '-q'])
    import pytz

NY_TZ = pytz.timezone('America/New_York')

# ─────────────────────────────────────────────
# 过滤规则定义
# ─────────────────────────────────────────────

STABLECOINS = {
    'usdt', 'usdc', 'busd', 'dai', 'fdusd', 'tusd', 'usdp', 'usdd',
    'usde', 'pyusd', 'frax', 'lusd', 'crvusd', 'susd', 'gusd',
    'paxg', 'xaut', 'usd1', 'eur', 'euri', 'usds', 'usdx', 'usd0',
    'tether', 'first-digital-usd', 'usd-coin', 'binance-usd'
}

MEMECOINS = {
    'shib', 'pepe', 'floki', 'bonk', 'wif', 'neiro', 'pengu',
    'meme', 'turbo', 'mog-coin', 'brett', 'popcat', 'bome', 'slerf',
    'sundog', 'goat', 'pnut', 'act', 'moodeng', 'ponke', 'myro',
    'baby-doge-coin', 'samoyedcoin', 'kishu-inu', 'dogelon-mars',
    'hoge-finance', 'akita-inu', 'saitama'
}

# ─────────────────────────────────────────────
# 内部工具函数
# ─────────────────────────────────────────────

def _get_markets(page=1, per_page=250):
    """从 CoinGecko 获取市值排行数据。"""
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        'vs_currency': 'usd',
        'order': 'market_cap_desc',
        'per_page': per_page,
        'page': page,
        'sparkline': False,
        'price_change_percentage': '24h'
    }
    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()
    return resp.json()

# ─────────────────────────────────────────────
# T0：获取原始标的池
# ─────────────────────────────────────────────

def get_t0(top_n=150) -> pd.DataFrame:
    """
    从 CoinGecko 市值前 300 中，剔除稳定币和模因币（保留 DOGE），
    返回前 top_n 名作为 T0 原始标的池。

    Returns:
        DataFrame: columns = [Rank, Symbol, CoinID, Name, MarketCap_USD, Price_USD, PriceChange24h]
    """
    rows = []
    for page in [1, 2]:
        data = _get_markets(page=page, per_page=250)
        for item in data:
            sym = item['symbol'].lower()
            cid = item['id'].lower()
            # 保留 DOGE，剔除其他模因币和稳定币
            if sym == 'doge':
                pass
            elif sym in STABLECOINS or cid in STABLECOINS:
                continue
            elif sym in MEMECOINS or cid in MEMECOINS:
                continue
            rows.append({
                'Symbol': item['symbol'].upper(),
                'CoinID': item['id'],
                'Name': item['name'],
                'MarketCap_USD': item.get('market_cap') or 0,
                'Price_USD': item.get('current_price') or 0,
                'PriceChange24h': item.get('price_change_percentage_24h') or 0,
                'Volume24h_USD': item.get('total_volume') or 0
            })
        time.sleep(0.5)  # 避免触发 API 频率限制

    df = pd.DataFrame(rows)
    df = df.sort_values('MarketCap_USD', ascending=False).head(top_n).reset_index(drop=True)
    df.insert(0, 'Rank', df.index + 1)
    return df


# ─────────────────────────────────────────────
# T1：从 T0 中按市值取前 50
# ─────────────────────────────────────────────

def get_t1(t0_df: pd.DataFrame = None, top_n=50) -> pd.DataFrame:
    """
    从 T0 标的池中按市值排序取前 top_n 名，作为本周核心观察表 T1。

    Args:
        t0_df: T0 DataFrame，若为 None 则自动调用 get_t0() 生成。
        top_n: 取前几名，默认 50。

    Returns:
        DataFrame: columns = [Rank, Symbol, CoinID, Name, MarketCap_USD, Price_USD, PriceChange24h, UpdatedAt_NY]
    """
    if t0_df is None:
        t0_df = get_t0()

    df = t0_df.sort_values('MarketCap_USD', ascending=False).head(top_n).reset_index(drop=True)
    df['Rank'] = df.index + 1
    now_ny = datetime.now(NY_TZ)
    df['UpdatedAt_NY'] = now_ny.strftime('%Y-%m-%d %H:%M:%S')
    return df


# ─────────────────────────────────────────────
# T2：获取单个标的的 K 线数据
# ─────────────────────────────────────────────

# CoinGecko days 参数与周期的映射
# days=1  → 约 5min 粒度
# days=7  → 约 1h 粒度
# days=30 → 约 4h 粒度
# days=90 → 约 1D 粒度

PERIOD_CONFIG = {
    '15min_2d': {'days': 2,  'label': '15min', 'approx': '~30min 粒度'},
    '1h_7d':    {'days': 7,  'label': '1h',    'approx': '~1h 粒度'},
    '4h_1mo':   {'days': 30, 'label': '4h',    'approx': '~4h 粒度'},
    '1d_3mo':   {'days': 90, 'label': '1D',    'approx': '~1D 粒度'},
}

def get_klines(coin_id: str, days: int) -> pd.DataFrame:
    """
    从 CoinGecko 获取指定标的的 OHLC K 线数据。

    Args:
        coin_id: CoinGecko 的 coin id，如 'bitcoin'、'ethereum'。
                 可从 get_t0() 或 get_t1() 返回的 CoinID 列获取。
        days:    历史天数。
                 - 2  → 约 30min 粒度
                 - 7  → 约 1h 粒度
                 - 30 → 约 4h 粒度
                 - 90 → 约 1D 粒度

    Returns:
        DataFrame: columns = [Open_Time_NY, Open, High, Low, Close]
                   Open_Time_NY 为纽约时间。

    示例：
        df = get_klines('bitcoin', 7)      # BTC 过去 7 天 1h K 线
        df = get_klines('ethereum', 30)    # ETH 过去 30 天 4h K 线
        df = get_klines('solana', 2)       # SOL 过去 2 天短周期 K 线
    """
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc"
    params = {'vs_currency': 'usd', 'days': days}
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        df = pd.DataFrame(data, columns=['Timestamp_ms', 'Open', 'High', 'Low', 'Close'])
        df['Open_Time_UTC'] = pd.to_datetime(df['Timestamp_ms'], unit='ms', utc=True)
        df['Open_Time_NY'] = df['Open_Time_UTC'].dt.tz_convert(NY_TZ).dt.strftime('%Y-%m-%d %H:%M:%S')
        for col in ['Open', 'High', 'Low', 'Close']:
            df[col] = df[col].astype(float)
        return df[['Open_Time_NY', 'Open', 'High', 'Low', 'Close']].reset_index(drop=True)
    except Exception as e:
        print(f"[get_klines] {coin_id} days={days} 获取失败: {e}")
        return pd.DataFrame()


# ─────────────────────────────────────────────
# T2：批量获取 T1 所有标的的多周期 K 线
# ─────────────────────────────────────────────

def get_t2(t1_df: pd.DataFrame = None, periods: list = None) -> dict:
    """
    批量获取 T1 中所有标的的多周期 K 线数据。

    Args:
        t1_df:   T1 DataFrame（需含 Symbol 和 CoinID 列），若为 None 则自动生成。
        periods: 周期列表，可选值：'15min_2d', '1h_7d', '4h_1mo', '1d_3mo'。
                 默认获取全部四个周期。

    Returns:
        dict: {
            'BTC': {
                '15min_2d': DataFrame,
                '1h_7d':    DataFrame,
                '4h_1mo':   DataFrame,
                '1d_3mo':   DataFrame
            },
            'ETH': { ... },
            ...
        }

    示例：
        t1 = get_t1()
        t2 = get_t2(t1)
        btc_1h = t2['BTC']['1h_7d']
        eth_4h = t2['ETH']['4h_1mo']
    """
    if t1_df is None:
        t1_df = get_t1()
    if periods is None:
        periods = list(PERIOD_CONFIG.keys())

    result = {row['Symbol']: {} for _, row in t1_df.iterrows()}
    coin_id_map = {row['Symbol']: row['CoinID'] for _, row in t1_df.iterrows()}

    def fetch(symbol, coin_id, period_key):
        days = PERIOD_CONFIG[period_key]['days']
        df = get_klines(coin_id, days)
        time.sleep(0.2)  # 避免触发频率限制
        return symbol, period_key, df

    tasks = [
        (sym, coin_id_map[sym], pk)
        for sym in result
        for pk in periods
    ]

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch, *task): task for task in tasks}
        for future in as_completed(futures):
            symbol, period_key, df = future.result()
            result[symbol][period_key] = df

    return result


# ─────────────────────────────────────────────
# 快捷调用示例（直接运行此文件时执行）
# ─────────────────────────────────────────────

if __name__ == '__main__':
    print("=== [T1] 获取市值前 50 观察表 ===")
    t1 = get_t1()
    print(t1[['Rank', 'Symbol', 'Name', 'MarketCap_USD', 'Price_USD', 'PriceChange24h']].to_string(index=False))

    print("\n=== [T2] 获取 BTC 过去 7 天 1h K 线（最新 5 根）===")
    btc_1h = get_klines('bitcoin', 7)
    print(btc_1h.tail(5).to_string(index=False))

    print("\n=== [T2] 获取 ETH 过去 30 天 4h K 线（最新 5 根）===")
    eth_4h = get_klines('ethereum', 30)
    print(eth_4h.tail(5).to_string(index=False))
