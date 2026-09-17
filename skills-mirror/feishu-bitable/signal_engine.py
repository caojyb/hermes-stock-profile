"""
信号引擎 - 四维度信号引擎 + 动态止损止盈

四维度权重：
- 技术面 (Technical): 40%
- 基本面 (Fundamental): 30%  
- 消息面 (News/Sentiment): 15%
- 情绪面 (Market Emotion): 15%

技术指标：
- RSI(14): 相对强弱指数
- MACD(12,26,9): 指数平滑异同移动平均线
- 布林带(20,2): 移动平均线和标准差
- ATR(20): 真实波幅均值
- 均线多头排列: 5/10/20/60日均线

动态止损止盈：
- 止损: max(成本价 - 2*ATR20, 最近支撑位)
- 止盈分批: 1倍ATR卖1/3，2倍ATR卖1/3，剩余看趋势

信号等级：0-5 (0=无信号, 5=强烈操作信号)
操作建议：持有/加仓/减仓/清仓/买入
"""

import sys
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime
import math

# 导入现有模块
from bitable_reader import BitableReader, PositionRecord
from stock_data import StockDataFetcher
from stock_data import get_stock_money_flow, get_market_rsi, _kline_amount_5d


# ============================================================
# 技术指标计算
# ============================================================

class TechnicalIndicators:
    """技术指标计算器"""

    @staticmethod
    def calculate_rsi(prices: List[float], period: int = 14) -> Optional[float]:
        """
        计算RSI(相对强弱指数)
        
        Args:
            prices: 收盘价列表
            period: 计算周期，默认14
            
        Returns:
            RSI值 (0-100)
        """
        if len(prices) < period + 1:
            return None
            
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        
        gains = [d if d > 0 else 0 for d in deltas[-period:]]
        losses = [-d if d < 0 else 0 for d in deltas[-period:]]
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100.0
            
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> Optional[List[float]]:
        """
        计算指数移动平均线 (EMA)
        
        Args:
            prices: 价格列表
            period: EMA周期
            
        Returns:
            EMA值列表
        """
        if len(prices) < period:
            return None
            
        ema = [sum(prices[:period]) / period]  # 初始值是简单平均
        
        multiplier = 2 / (period + 1)
        for price in prices[period:]:
            ema.append((price - ema[-1]) * multiplier + ema[-1])
            
        return ema

    @staticmethod
    def calculate_macd(
        prices: List[float], 
        fast: int = 12, 
        slow: int = 26, 
        signal: int = 9
    ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """
        计算MACD指标
        
        Args:
            prices: 收盘价列表
            fast: 快线周期，默认12
            slow: 慢线周期，默认26
            signal: 信号线周期，默认9
            
        Returns:
            (MACD线, 信号线, 柱状图)
        """
        if len(prices) < slow + signal:
            return None, None, None
            
        # 计算快线和慢线EMA
        ema_fast = TechnicalIndicators.calculate_ema(prices, fast)
        ema_slow = TechnicalIndicators.calculate_ema(prices, slow)
        
        if ema_fast is None or ema_slow is None:
            return None, None, None
            
        # MACD线 = 快线EMA - 慢线EMA
        macd_line = [ema_fast[i] - ema_slow[i] for i in range(len(ema_slow))]
        
        # 计算信号线 (MACD的EMA)
        if len(macd_line) < signal:
            return None, None, None
            
        signal_line = TechnicalIndicators.calculate_ema(macd_line, signal)
        
        if signal_line is None or len(macd_line) < 1:
            return None, None, None
            
        current_macd = macd_line[-1]
        current_signal = signal_line[-1]
        histogram = current_macd - current_signal
        
        return current_macd, current_signal, histogram

    @staticmethod
    def calculate_bollinger_bands(
        prices: List[float], 
        period: int = 20, 
        std_dev: int = 2
    ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """
        计算布林带
        
        Args:
            prices: 收盘价列表
            period: 周期，默认20
            std_dev: 标准差倍数，默认2
            
        Returns:
            (中轨MA, 上轨, 下轨)
        """
        if len(prices) < period:
            return None, None, None
            
        recent_prices = prices[-period:]
        ma = sum(recent_prices) / period
        
        # 计算标准差
        variance = sum((p - ma) ** 2 for p in recent_prices) / period
        std = math.sqrt(variance)
        
        upper_band = ma + std_dev * std
        lower_band = ma - std_dev * std
        
        return ma, upper_band, lower_band

    @staticmethod
    def calculate_atr(
        klines: List[Dict[str, Any]], 
        period: int = 20
    ) -> Optional[float]:
        """
        计算ATR(真实波幅均值)
        
        Args:
            klines: K线数据列表，每项包含 high, low, close
            period: 周期，默认20
            
        Returns:
            ATR值
        """
        if len(klines) < period + 1:
            return None
            
        true_ranges = []
        for i in range(1, len(klines)):
            high = klines[i]['high']
            low = klines[i]['low']
            prev_close = klines[i-1]['close']
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)
        
        if len(true_ranges) < period:
            return None
            
        atr = sum(true_ranges[-period:]) / period
        return atr

    @staticmethod
    def calculate_ma_alignment(prices: List[float]) -> Dict[str, Any]:
        """
        计算均线多头/空头排列
        
        Args:
            prices: 收盘价列表
            
        Returns:
            均线排列状态
        """
        ma_periods = [5, 10, 20, 60]
        ma_values = {}
        
        for period in ma_periods:
            if len(prices) >= period:
                ma_values[period] = sum(prices[-period:]) / period
            else:
                ma_values[period] = None
        
        # 检查多头排列 (短期 > 长期)
        if all(v is not None for v in ma_values.values()):
            bullish = (
                ma_values[5] > ma_values[10] > ma_values[20] > ma_values[60]
            )
            bearish = (
                ma_values[5] < ma_values[10] < ma_values[20] < ma_values[60]
            )
            
            # 计算各均线间距
            spacings = {}
            for i, p1 in enumerate(ma_periods[:-1]):
                p2 = ma_periods[i + 1]
                if ma_values[p1] and ma_values[p2]:
                    spacings[p1] = (ma_values[p1] - ma_values[p2]) / ma_values[p2] * 100
            
            return {
                "bullish": bullish,
                "bearish": bearish,
                "neutral": not bullish and not bearish,
                "ma_values": ma_values,
                "spacings": spacings
            }
        
        return {
            "bullish": False,
            "bearish": False,
            "neutral": True,
            "ma_values": ma_values,
            "spacings": {}
        }

    @staticmethod
    def find_support_resistance(
        klines: List[Dict[str, Any]], 
        lookback: int = 20
    ) -> Dict[str, float]:
        """
        查找支撑位和阻力位
        
        Args:
            klines: K线数据
            lookback: 回溯周期
            
        Returns:
            (支撑位, 阻力位)
        """
        if len(klines) < lookback:
            lookback = len(klines)
            
        recent_klines = klines[-lookback:]
        
        lows = [k['low'] for k in recent_klines]
        highs = [k['high'] for k in recent_klines]
        
        # 最近20天最低价作为支撑
        support = min(lows)
        # 最近20天最高价作为阻力
        resistance = max(highs)
        
        return {
            "support": support,
            "resistance": resistance
        }


# ============================================================
# 信号评分
# ============================================================

@dataclass
class SignalScore:
    """信号评分"""
    total_score: float = 0.0          # 总分 (0-100)
    signal_level: int = 0             # 信号等级 (0-5)
    
    # 分项得分
    technical_score: float = 0.0       # 技术面得分 (0-100)
    fundamental_score: float = 0.0     # 基本面得分 (0-100)
    news_score: float = 0.0           # 消息面得分 (0-100)
    emotion_score: float = 0.0        # 情绪面得分 (0-100)
    
    # 技术指标详情
    rsi: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_histogram: Optional[float] = None
    boll_upper: Optional[float] = None
    boll_middle: Optional[float] = None
    boll_lower: Optional[float] = None
    atr: Optional[float] = None
    ma_alignment: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TradingAdvice:
    """交易建议"""
    action: str                        # 操作: 买入/加仓/持有/减仓/清仓
    signal_level: int                  # 信号等级 (0-5)
    confidence: float                  # 置信度 (0-1)
    
    # 动态止损止盈
    stop_loss: float                   # 止损价
    take_profit_1: float               # 第一止盈价 (1倍ATR)
    take_profit_2: float               # 第二止盈价 (2倍ATR)
    take_profit_3: Optional[float] = None  # 第三止盈价 (趋势止盈)
    
    # 支撑阻力
    support: float = 0.0
    resistance: float = 0.0
    
    # 原因说明
    reasons: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class StockSignal:
    """股票完整信号"""
    stock_code: str
    stock_name: str
    
    # 持仓信息
    quantity: float
    cost_price: float
    current_price: float
    profit_loss: float
    profit_pct: float
    
    # 信号评分
    score: SignalScore
    
    # 交易建议
    advice: TradingAdvice
    
    def to_dict(self) -> dict:
        return {
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "quantity": self.quantity,
            "cost_price": self.cost_price,
            "current_price": self.current_price,
            "profit_loss": self.profit_loss,
            "profit_pct": self.profit_pct,
            "score": self.score.to_dict(),
            "advice": self.advice.to_dict()
        }


# ============================================================
# 四维度信号引擎
# ============================================================

class SignalEngine:
    """
    四维度信号引擎
    
    维度权重:
    - 技术面: 40%
    - 基本面: 30%
    - 消息面: 15%
    - 情绪面: 15%
    """
    
    # 维度权重
    WEIGHTS = {
        "technical": 0.40,
        "fundamental": 0.30,
        "news": 0.15,
        "emotion": 0.15
    }
    
    def __init__(self):
        self.data_fetcher = StockDataFetcher()
        self.tech = TechnicalIndicators()
        self._market_rsi_cache = None  # 大盘RSI缓存（全市场只需查一次）
        self._money_flow_cache = {}     # 个股资金流缓存 {code: data}
        
    def get_kline_data(self, stock_code: str, days: int = 65) -> List[Dict[str, Any]]:
        """
        获取K线数据
        
        Args:
            stock_code: 股票代码 (6位数字)
            days: 天数
            
        Returns:
            K线数据列表
        """
        # 添加市场前缀（北交所: 4/8/920开头）
        if stock_code.startswith(('4', '8', '920')):
            market = 'bj'
        elif stock_code.startswith('6'):
            market = 'sh'
        else:
            market = 'sz'
            
        result = self.data_fetcher.get_a_share_kline(f"{market}{stock_code}", days)
        
        if "error" in result:
            return []
            
        return result.get("klines", [])
    
    def get_realtime_quote(self, stock_code: str) -> Dict[str, Any]:
        """
        获取实时行情
        
        Args:
            stock_code: 股票代码
            
        Returns:
            行情数据
        """
        # 添加市场前缀（北交所: 4/8/920开头）
        if stock_code.startswith(('4', '8', '920')):
            market = 'bj'
        elif stock_code.startswith('6'):
            market = 'sh'
        else:
            market = 'sz'
            
        return self.data_fetcher.get_a_share_quote(f"{market}{stock_code}")
    
    def calculate_technical_score(
        self, 
        klines: List[Dict[str, Any]], 
        current_price: float
    ) -> Tuple[float, SignalScore]:
        """
        计算技术面得分
        
        Args:
            klines: K线数据
            current_price: 当前价格
            
        Returns:
            (技术面得分, 技术指标详情)
        """
        if len(klines) < 30:
            return 0.0, SignalScore()
            
        closes = [k['close'] for k in klines]
        
        # 计算各项技术指标
        rsi = self.tech.calculate_rsi(closes, 14)
        macd, macd_signal, histogram = self.tech.calculate_macd(closes)
        boll_mid, boll_upper, boll_lower = self.tech.calculate_bollinger_bands(closes)
        atr = self.tech.calculate_atr(klines, 20)
        ma_alignment = self.tech.calculate_ma_alignment(closes)
        support_resistance = self.tech.find_support_resistance(klines)
        
        score = 0.0
        factors = 0
        
        # 1. RSI评分 (权重约20%)
        if rsi is not None:
            factors += 1
            if 30 <= rsi <= 70:
                # 正常区间，得分适中
                if rsi < 30:
                    score += 40  # 超卖，低风险
                elif rsi > 70:
                    score += 30  # 超买，风险较高
                else:
                    score += 60  # 正常区域
            elif rsi < 20:
                score += 80  # 严重超卖，极佳买点
            elif rsi > 80:
                score += 10  # 严重超买，风险极大
        
        # 2. MACD评分 (权重约25%)
        if macd is not None and macd_signal is not None:
            factors += 1
            if histogram > 0 and macd > macd_signal:
                score += 70  # 金叉多头
            elif histogram < 0 and macd < macd_signal:
                score += 20  # 死叉空头
            elif histogram > 0:
                score += 55  # MACD上升
            else:
                score += 35  # MACD下降
        
        # 3. 布林带评分 (权重约15%)
        if boll_mid is not None:
            factors += 1
            if current_price < boll_lower:
                score += 85  # 触及下轨，超卖
            elif current_price > boll_upper:
                score += 25  # 触及上轨，超买
            else:
                # 计算价格在中轨的位置
                position = (current_price - boll_mid) / (boll_upper - boll_lower) if boll_upper != boll_lower else 0.5
                if 0.3 <= position <= 0.7:
                    score += 60  # 正常区域
                elif position < 0.3:
                    score += 75  # 偏向下轨，有上涨空间
                else:
                    score += 40  # 偏向上轨，有下跌风险
        
        # 4. 均线多头排列 (权重约25%)
        if ma_alignment:
            factors += 1
            if ma_alignment["bullish"]:
                score += 80  # 多头排列，强势
            elif ma_alignment["bearish"]:
                score += 20  # 空头排列，弱势
            else:
                score += 45  # 混乱排列
        
        # 5. 趋势强度 (权重约15%)
        if atr is not None and current_price > 0:
            # ATR占价格的百分比，越大说明波动越大
            atr_pct = atr / current_price * 100
            if atr_pct < 2:
                score += 60  # 低波动，稳定
            elif atr_pct < 5:
                score += 50  # 正常波动
            else:
                score += 35  # 高波动，风险较大
        
        # 标准化得分
        if factors > 0:
            raw_score = score / factors * (100 / 70)  # 归一化到0-100
            technical_score = min(100, max(0, raw_score))
        else:
            technical_score = 50.0  # 默认中性
        
        # 构建技术指标详情
        tech_details = SignalScore(
            technical_score=technical_score,
            rsi=rsi,
            macd=macd,
            macd_signal=macd_signal,
            macd_histogram=histogram,
            boll_upper=boll_upper,
            boll_middle=boll_mid,
            boll_lower=boll_lower,
            atr=atr,
            ma_alignment=ma_alignment
        )
        
        return technical_score, tech_details
    
    def calculate_fundamental_score(self, position: PositionRecord) -> float:
        """
        计算基本面得分 (简化版)
        
        实际应用中应该调用 fundamental.py 获取详细数据
        """
        # 简化：基于持仓周期和盈亏评估
        score = 50.0
        
        # 持仓周期评分
        if position.period == "短线":
            score += 10  # 短线持仓要求更严格
        elif position.period == "中线":
            score += 5
        
        # 行业评分 (简化)
        if position.industry:
            # 简单处理：能源、金融等权重行业给点加分
            stable_sectors = ["银行", "保险", "能源", "公用事业"]
            growth_sectors = ["科技", "医药", "新能源"]
            
            if any(s in position.industry for s in stable_sectors):
                score += 5
            elif any(s in position.industry for s in growth_sectors):
                score += 3
        
        return min(100, max(0, score))
    
    def get_market_rsi_cached(self) -> Optional[float]:
        """获取大盘RSI（带缓存，只查一次）"""
        if self._market_rsi_cache is None:
            self._market_rsi_cache = get_market_rsi("sh000300", 14)
        return self._market_rsi_cache

    def calculate_news_score(self, position: PositionRecord,
                             quote: Optional[Dict[str, Any]] = None,
                             klines: Optional[List[Dict[str, Any]]] = None) -> float:
        """
        计算消息面得分
        融合：涨跌幅度 + 主力资金流向（Step 1）
        - 主力净流入占比 > 20% → 机构买入 → +15~25分
        - 主力净流出占比 > 20% → 机构抛售 → -15~-25分
        - 今日涨幅 > 9% → 追高风险 → -15分
        - 今日跌幅 > 5% → 超卖反弹机会 → +10分
        """
        score = 50.0
        change_pct = position.change_pct

        # === 资金流评分（最重要）===
        code = position.stock_code
        if code not in self._money_flow_cache:
            # 单位链: quote.turnover(万元,腾讯原始) → ×1e4 → 元; 5日分母=日K amount(万元)求和×1e4
            turnover_wan = quote.get("turnover") if quote else None
            turnover_yuan = turnover_wan * 1e4 if turnover_wan is not None else None
            turnover_5d_yuan = _kline_amount_5d(klines)
            self._money_flow_cache[code] = get_stock_money_flow(
                code, days=5,
                turnover_yuan=turnover_yuan,
                turnover_5d_yuan=turnover_5d_yuan)
        mf = self._money_flow_cache[code]

        if "error" not in mf:
            # None = 分母缺失(行情/K线未取到), 与0一样按中性处理, 不参与分档
            days_main_pct = mf.get("days_main_pct") or 0
            main_pct = mf.get("main_pct") or 0

            # 5日主力净流入占比（均值）
            if days_main_pct > 20:
                score += 25  # 连续5日主力强势买入
            elif days_main_pct > 10:
                score += 15
            elif days_main_pct > 0:
                score += 8
            elif days_main_pct < -20:
                score -= 25  # 连续5日主力砸盘
            elif days_main_pct < -10:
                score -= 15
            elif days_main_pct < 0:
                score -= 8

            # 今日主力净流入方向（强化信号）
            if main_pct > 30:
                score += 10  # 今日主力爆买
            elif main_pct < -30:
                score -= 10  # 今日主力砸盘
        else:
            # 资金流API不可用，降级到涨跌评估
            import sys as _sys
            print(f"[WARN] money_flow degraded: code={position.stock_code} reason={mf.get('error', 'unknown')}",
                  file=_sys.stderr)
            # 降级日志: 追加到 stock-work/data/runtime/（10MB 轮转留一份 .1）
            # stderr 在 cron 成功时被丢弃，此文件是降级率的唯一持久观测点
            try:
                import os as _os
                from datetime import datetime as _dt
                _log = _os.path.expanduser(
                    "~/.hermes/profiles/stock/stock-work/data/runtime/money_flow_degraded.log")
                if _os.path.exists(_log) and _os.path.getsize(_log) > 10 * 1024 * 1024:
                    _os.rename(_log, _log + ".1")
                with open(_log, "a", encoding="utf-8") as _f:
                    _f.write(f"{_dt.now().isoformat()} code={position.stock_code} "
                             f"reason={mf.get('error', 'unknown')}\n")
            except Exception:
                pass  # 日志失败不影响主流程
            if change_pct > 9:
                score -= 15
            elif change_pct > 5:
                score -= 8
            elif change_pct < -5:
                score += 10
            elif change_pct < -2:
                score += 5

        # === 涨跌幅度评分（辅助）===
        if "error" not in mf:
            # 已有资金流数据，涨跌评估只做微调
            if change_pct > 9:
                score -= 10  # 涨幅过大，透支利好
            elif change_pct > 5:
                score -= 5
            elif change_pct < -5:
                score += 5   # 超跌有反弹可能
            elif change_pct < -2:
                score += 3

        return min(100, max(0, score))

    def calculate_emotion_score(self, position: PositionRecord) -> float:
        """
        计算情绪面得分
        融合：个股波动 + 大盘情绪过滤（Step 2）
        - 大盘 RSI > 80 → 过度乐观 → 抑制追涨信号 → -20分
        - 大盘 RSI < 30 → 过度悲观 → 鼓励抄底 → +20分
        - 个股今日涨幅 → 动能评估
        """
        score = 50.0

        # === 大盘情绪过滤（Step 2 核心）===
        market_rsi = self.get_market_rsi_cached()
        if market_rsi is not None:
            if market_rsi > 80:
                # 大盘超买：抑制做多，警告追高风险
                score -= 20
            elif market_rsi > 70:
                score -= 10
            elif market_rsi < 30:
                # 大盘超卖：鼓励逢低吸纳
                score += 20
            elif market_rsi < 40:
                score += 10
        # else: 大盘RSI获取失败，维持中性

        # === 个股动能评估 ===
        if position.change_pct > 0:
            # 上涨动能（和资金流方向结合更准）
            code = position.stock_code
            mf = self._money_flow_cache.get(code, {})
            main_pct = (mf.get("main_pct") or 0) if "error" not in mf else 0
            if main_pct > 10:
                # 主力流入 + 上涨 = 机构推动，上涨持续性更好
                score += 8
            else:
                score += (position.change_pct / 2) * 8
        else:
            # 下跌压力
            score -= (abs(position.change_pct) / 2) * 8

        return min(100, max(0, score))
    
    def calculate_signal_score(self, position: PositionRecord) -> SignalScore:
        """
        计算综合信号评分
        
        Args:
            position: 持仓记录
            
        Returns:
            信号评分
        """
        # 获取K线数据
        klines = self.get_kline_data(position.stock_code, days=65)
        
        # 获取实时价格
        quote = self.get_realtime_quote(position.stock_code)
        current_price = quote.get('price', position.current_price)
        
        # 计算技术面得分
        technical_score, tech_details = self.calculate_technical_score(klines, current_price)
        
        # 计算其他维度得分 (简化)
        fundamental_score = self.calculate_fundamental_score(position)
        # 传递已获取的行情/K线作资金流分母(方案1: 零新HTTP调用)
        news_score = self.calculate_news_score(position, quote=quote, klines=klines)
        emotion_score = self.calculate_emotion_score(position)
        
        # 加权综合得分
        total_score = (
            technical_score * self.WEIGHTS["technical"] +
            fundamental_score * self.WEIGHTS["fundamental"] +
            news_score * self.WEIGHTS["news"] +
            emotion_score * self.WEIGHTS["emotion"]
        )
        
        # 计算信号等级 (0-5)
        signal_level = self._score_to_level(total_score)
        
        # 更新技术指标详情
        tech_details.total_score = total_score
        tech_details.signal_level = signal_level
        tech_details.fundamental_score = fundamental_score
        tech_details.news_score = news_score
        tech_details.emotion_score = emotion_score
        
        return tech_details
    
    def _score_to_level(self, score: float) -> int:
        """
        将分数转换为信号等级
        
        Args:
            score: 总分 (0-100)
            
        Returns:
            信号等级 (0-5)
        """
        if score >= 85:
            return 5  # 强烈买入
        elif score >= 70:
            return 4  # 较强买入
        elif score >= 55:
            return 3  # 轻度买入/持有
        elif score >= 40:
            return 2  # 中性
        elif score >= 25:
            return 1  # 轻度卖出
        else:
            return 0  # 强烈卖出
    
    def calculate_trading_advice(
        self, 
        position: PositionRecord, 
        score: SignalScore
    ) -> TradingAdvice:
        """
        计算交易建议 (含动态止损止盈)
        
        Args:
            position: 持仓记录
            score: 信号评分
            
        Returns:
            交易建议
        """
        # 获取实时价格
        quote = self.get_realtime_quote(position.stock_code)
        current_price = quote.get('price', position.current_price)
        
        # 获取K线数据计算ATR
        klines = self.get_kline_data(position.stock_code, days=65)
        atr = self.tech.calculate_atr(klines, 20) if klines else None
        
        # 支撑阻力位
        support_resistance = self.tech.find_support_resistance(klines) if klines else {
            "support": current_price * 0.95,
            "resistance": current_price * 1.05
        }
        
        # 计算成本价到当前价的盈亏
        cost_price = position.cost_price
        profit_pct = (current_price - cost_price) / cost_price * 100 if cost_price > 0 else 0
        
        # ???????????ATR??????????
        # 止损?现价 - 2?ATR (?????????)
        # 止盈?现价 + N?ATR (????????????)
        if atr is not None and atr > 0:
            stop_loss = current_price - 2 * atr
            take_profit_1 = current_price + 1 * atr
            take_profit_2 = current_price + 2 * atr
            take_profit_3 = current_price + 3 * atr
        else:
            stop_loss = current_price * 0.95
            take_profit_1 = current_price * 1.05
            take_profit_2 = current_price * 1.10
            take_profit_3 = current_price * 1.15
        
        # 确定操作建议
        action, confidence, reasons = self._determine_action(
            position, score, current_price, stop_loss, atr
        )
        
        return TradingAdvice(
            action=action,
            signal_level=score.signal_level,
            confidence=confidence,
            stop_loss=stop_loss,
            take_profit_1=take_profit_1,
            take_profit_2=take_profit_2,
            take_profit_3=take_profit_3,
            support=support_resistance["support"],
            resistance=support_resistance["resistance"],
            reasons=reasons
        )
    
    def _determine_action(
        self,
        position: PositionRecord,
        score: SignalScore,
        current_price: float,
        stop_loss: float,
        atr: Optional[float]
    ) -> Tuple[str, float, List[str]]:
        """
        基于纯技术分析的客观操作建议
        不参考任何持仓数据
        """
        reasons = []
        confidence = 0.5

        sl = score.signal_level
        rsi = score.rsi
        macd_hist = score.macd_histogram if score.macd is not None else 0
        ma_bullish = score.ma_alignment.get("bullish", False) if score.ma_alignment else False
        ma_bearish = score.ma_alignment.get("bearish", False) if score.ma_alignment else False
        boll_lower = score.boll_lower
        boll_upper = score.boll_upper

        if sl >= 4:
            # 强信号：技术面支持上涨
            if rsi and rsi < 70:
                if rsi < 30:
                    reasons.append(f"RSI={rsi:.1f}严重超卖，反弹概率大")
                elif rsi < 50:
                    reasons.append(f"RSI={rsi:.1f}处于低位，向上空间充足")
                else:
                    reasons.append(f"RSI={rsi:.1f}健康上升区间")
            if ma_bullish:
                reasons.append("均线多头排列，上涨趋势清晰")
            if macd_hist > 0:
                reasons.append("MACD红柱，短期动能向上")
            confidence = 0.80 + (sl - 4) * 0.05
            return "买入", min(confidence, 0.95), reasons

        elif sl == 3:
            # 中性信号：方向不明，持有观察
            if rsi:
                if rsi > 70:
                    reasons.append(f"RSI={rsi:.1f}偏高，短期有回调风险")
                elif rsi < 30:
                    reasons.append(f"RSI={rsi:.1f}偏低，有反弹可能")
                else:
                    reasons.append(f"RSI={rsi:.1f}处于中性区间")
            if ma_bullish:
                reasons.append("均线多头，但上涨动力有限")
            elif ma_bearish:
                reasons.append("均线空头，下跌趋势未改")
            else:
                reasons.append("均线纠缠，方向待确认")
            if macd_hist < 0:
                reasons.append("MACD绿柱，动能偏弱")
            return "持有", 0.60, reasons

        elif sl == 2:
            # 偏弱信号：谨慎观望
            if rsi:
                if rsi > 60:
                    reasons.append(f"RSI={rsi:.1f}偏高，上涨乏力")
                elif rsi < 40:
                    reasons.append(f"RSI={rsi:.1f}偏低，但未到超卖")
            if ma_bearish:
                reasons.append("均线空头排列，下跌趋势中")
            reasons.append("技术面偏弱，建议观望")
            return "观望", 0.50, reasons

        elif sl <= 1:
            # 弱信号：减仓或止损
            if rsi and rsi > 60:
                reasons.append(f"RSI={rsi:.1f}高位，上涨难持续")
            if ma_bearish:
                reasons.append("均线空头，下跌趋势明显")
            if macd_hist < 0 and abs(macd_hist) > 1:
                reasons.append("MACD绿柱放大，动能较弱")
            # 如果现价接近止损位，提示止损风险
            if stop_loss > 0 and (current_price - stop_loss) / current_price < 0.08:
                reasons.append(f"现价距止损仅{((current_price-stop_loss)/current_price*100):.1f}%，风险较高")
            confidence = 0.65 + (1 - sl) * 0.05
            return "减仓", min(confidence, 0.80), reasons

        return "观望", 0.50, ["信号不明确"]
    
    def analyze_position(self, position: PositionRecord) -> StockSignal:
        """
        完整分析一只股票
        
        Args:
            position: 持仓记录
            
        Returns:
            完整信号报告
        """
        # 计算信号评分
        score = self.calculate_signal_score(position)
        
        # 获取实时价格更新
        quote = self.get_realtime_quote(position.stock_code)
        current_price = quote.get('price', position.current_price)
        
        # 计算盈亏
        cost_price = position.cost_price
        profit_loss = (current_price - cost_price) * position.quantity
        profit_pct = (current_price - cost_price) / cost_price * 100 if cost_price > 0 else 0
        
        # 计算交易建议
        advice = self.calculate_trading_advice(position, score)
        
        return StockSignal(
            stock_code=position.stock_code,
            stock_name=position.stock_name,
            quantity=position.quantity,
            cost_price=cost_price,
            current_price=current_price,
            profit_loss=profit_loss,
            profit_pct=profit_pct,
            score=score,
            advice=advice
        )
    
    def analyze_all_positions(self) -> List[StockSignal]:
        """
        分析所有持仓
        
        Returns:
            信号报告列表
        """
        try:
            reader = BitableReader()
            positions = reader.get_hold_positions()
            
            signals = []
            for pos in positions:
                if pos.stock_code and pos.quantity > 0:
                    try:
                        signal = self.analyze_position(pos)
                        signals.append(signal)
                    except Exception as e:
                        print(f"分析 {pos.stock_code} 失败: {e}")
                        continue
            
            return signals
            
        except Exception as e:
            print(f"读取持仓失败: {e}")
            return []
    
    def generate_signal_report(self, signals: List[StockSignal]) -> str:
        """
        生成信号报告文本
        
        Args:
            signals: 信号列表
            
        Returns:
            格式化报告
        """
        if not signals:
            return "暂无持仓信号"
        
        lines = ["=" * 60]
        lines.append("【四维度信号引擎 - 持仓分析报告】")
        lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("=" * 60)
        
        for sig in signals:
            lines.append("")
            lines.append(f"【{sig.stock_name}({sig.stock_code})】")
            lines.append("-" * 40)
            
            # 持仓信息
            lines.append(f"持仓: {sig.quantity}股 | 成本: {sig.cost_price:.3f} | 现价: {sig.current_price:.3f}")
            lines.append(f"盈亏: {sig.profit_loss:+.2f}元 ({sig.profit_pct:+.2f}%)")
            
            # 信号评分
            lines.append("")
            lines.append("【信号评分】")
            score = sig.score
            lines.append(f"  综合得分: {score.total_score:.1f}/100 (等级{score.signal_level})")
            lines.append(f"  技术面: {score.technical_score:.1f} | 基本面: {score.fundamental_score:.1f}")
            lines.append(f"  消息面: {score.news_score:.1f} | 情绪面: {score.emotion_score:.1f}")
            
            # 技术指标
            lines.append("")
            lines.append("【技术指标】")
            if score.rsi is not None:
                lines.append(f"  RSI(14): {score.rsi:.1f}")
            if score.macd is not None:
                lines.append(f"  MACD: {score.macd:.3f} (信号线: {score.macd_signal:.3f}, 柱: {score.macd_histogram:.3f})")
            if score.atr is not None:
                lines.append(f"  ATR(20): {score.atr:.3f}")
            if score.ma_alignment:
                if score.ma_alignment.get("bullish"):
                    lines.append("  均线: 多头排列")
                elif score.ma_alignment.get("bearish"):
                    lines.append("  均线: 空头排列")
                else:
                    lines.append("  均线: 混乱排列")
            
            # 交易建议
            lines.append("")
            lines.append("【交易建议】")
            advice = sig.advice
            lines.append(f"  操作: {advice.action} (置信度: {advice.confidence:.0%})")
            lines.append(f"  止损: {advice.stop_loss:.3f}")
            lines.append(f"  止盈1: {advice.take_profit_1:.3f} | 止盈2: {advice.take_profit_2:.3f}")
            if advice.take_profit_3:
                lines.append(f"  止盈3: {advice.take_profit_3:.3f}")
            lines.append(f"  支撑: {advice.support:.3f} | 阻力: {advice.resistance:.3f}")
            
            if advice.reasons:
                lines.append("  原因:")
                for r in advice.reasons:
                    lines.append(f"    - {r}")
            
            lines.append("")
        
        lines.append("=" * 60)
        lines.append("【权重说明】技术40% + 基本面30% + 消息15% + 情绪15%")
        lines.append("【免责声明】仅供参考，不构成投资建议")
        lines.append("=" * 60)
        
        return "\n".join(lines)


# ============================================================
# 主程序入口
# ============================================================

def main():
    """主程序"""
    engine = SignalEngine()
    
    print("正在获取持仓并分析...")
    
    try:
        # 分析所有持仓
        signals = engine.analyze_all_positions()
        
        # 生成报告
        report = engine.generate_signal_report(signals)
        print(report)
        
        # 也可以输出JSON格式
        # import json
        # print(json.dumps([s.to_dict() for s in signals], ensure_ascii=False, indent=2))
        
    except Exception as e:
        print(f"分析失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
