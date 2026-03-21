# Crypto Market Data Hub

**市场交易项目 - Crypto 数据共享中枢**

本仓库作为 Manus 项目「市场交易」下所有 Agent 的统一数据源，提供实时更新的加密货币市场数据。

---

## 数据体系说明

| 文件 | 说明 | 更新频率 |
|---|---|---|
| `T0_Crypto_Base.csv` | 原始标的池：市值前 150，已剔除稳定币和模因币（保留 DOGE） | 每周一 NY 08:00 |
| `T1_Weekly_Observation.csv` | 每周观察表：从 T0 中按市值取前 50 名 | 每周一 NY 08:00 |
| `crypto_data_api.py` | 标准化数据接口模块，支持实时调取 T0/T1/T2 数据 | 随代码更新 |

---

## 快速调用（其他 Agent 使用方式）

### 第一步：下载数据接口模块

```bash
wget -q -O /home/ubuntu/crypto_data_api.py \
  https://raw.githubusercontent.com/flowersfallinthegardentree/crypto-market-data/main/crypto_data_api.py
```

### 第二步：下载最新 T0/T1 数据

```bash
# T0 原始标的池
wget -q -O /home/ubuntu/T0_Crypto_Base.csv \
  https://raw.githubusercontent.com/flowersfallinthegardentree/crypto-market-data/main/T0_Crypto_Base.csv

# T1 每周观察表
wget -q -O /home/ubuntu/T1_Weekly_Observation.csv \
  https://raw.githubusercontent.com/flowersfallinthegardentree/crypto-market-data/main/T1_Weekly_Observation.csv
```

### 第三步：实时调取数据（Python）

```python
from crypto_data_api import get_t0, get_t1, get_klines, get_t2

# 获取 T1（市值前 50 观察表）
t1 = get_t1()

# 获取单个标的 K 线（coin_id 来自 T1 的 CoinID 列）
btc_1h  = get_klines('bitcoin',   7)    # 过去 7 天 ~1h 粒度
eth_4h  = get_klines('ethereum',  30)   # 过去 30 天 ~4h 粒度
sol_2d  = get_klines('solana',    2)    # 过去 2 天 ~30min 粒度
btc_3mo = get_klines('bitcoin',   90)   # 过去 3 个月 ~1D 粒度

# 批量获取 T1 所有标的的多周期 K 线
t2 = get_t2(t1)
btc_4h = t2['BTC']['4h_1mo']
eth_1h = t2['ETH']['1h_7d']
```

---

## K 线周期说明

| 参数 `days` | 数据粒度 | 对应 T2 周期 |
|---|---|---|
| `2` | ~30min | `15min_2d` |
| `7` | ~1h | `1h_7d` |
| `30` | ~4h | `4h_1mo` |
| `90` | ~1D | `1d_3mo` |

> **时区基准**：所有时间戳均已转换为**纽约时间（America/New_York）**，以 NY 08:00 为 4h 周期锚点。

---

## 数据来源

- **市值与价格**：[CoinGecko API](https://www.coingecko.com/en/api)（免费，无需 API Key）
- **K 线数据**：[CoinGecko OHLC API](https://www.coingecko.com/en/api/documentation)

---

*本仓库由 Manus Agent 自动维护，数据每周一纽约时间 08:00 更新。*
