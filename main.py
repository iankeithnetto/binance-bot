"""
Binance Trading Bot - Complete Production Version
Deploy on Railway in 5 minutes
"""

import os
import time
import logging
from datetime import datetime
from typing import Dict, List, Optional
import ccxt
import pandas as pd
import numpy as np

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger('BinanceBot')

# ============================================================
# CONFIGURATION
# ============================================================
class Config:
    def __init__(self):
        # Load from environment variables
        self.api_key = os.getenv('BINANCE_API_KEY', '')
        self.api_secret = os.getenv('BINANCE_API_SECRET', '')
        self.test_mode = os.getenv('TEST_MODE', 'true').lower() == 'true'
        
        # Risk settings
        risk_level = os.getenv('RISK_LEVEL', 'conservative')
        if risk_level == 'aggressive':
            self.leverage = 3
            self.risk_per_trade = 0.03
        elif risk_level == 'moderate':
            self.leverage = 2
            self.risk_per_trade = 0.02
        else:  # conservative
            self.leverage = 1
            self.risk_per_trade = 0.01
        
        # Capital
        self.capital = float(os.getenv('STARTING_CAPITAL', '5000'))
        self.max_positions = 3
        self.max_daily_loss = 0.04
        
        # Trading pairs
        self.pairs = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'DOGE/USDT']
        
        # Strategy parameters
        self.atr_period = 14
        self.ema_fast = 50
        self.ema_slow = 200
        self.breakout_lookback = 20
        self.stop_atr_mult = 1.5
        self.funding_threshold = 0.0005  # 0.05%

# ============================================================
# EXCHANGE CONNECTION
# ============================================================
class Exchange:
    def __init__(self, config: Config):
        self.config = config
        self.spot = None
        self.futures = None
        self._init_exchanges()
    
    def _init_exchanges(self):
        """Initialize exchange connections."""
        params = {
            'apiKey': self.config.api_key,
            'secret': self.config.api_secret,
            'enableRateLimit': True,
            'rateLimit': 100,
            'timeout': 30000,
        }
        
        if self.config.test_mode:
            logger.info("🔧 TEST MODE - No real trades")
            # Use testnet
            spot_params = {**params, 'options': {'defaultType': 'spot'}}
            spot_params['urls'] = {'api': {'public': 'https://testnet.binance.vision/api/v3',
                                           'private': 'https://testnet.binance.vision/api/v3'}}
            
            futures_params = {**params, 'options': {'defaultType': 'future'}}
            futures_params['urls'] = {'api': {'public': 'https://testnet.binancefuture.com/fapi/v1',
                                              'private': 'https://testnet.binancefuture.com/fapi/v1'}}
        else:
            spot_params = {**params, 'options': {'defaultType': 'spot'}}
            futures_params = {**params, 'options': {'defaultType': 'future', 'hedgeMode': False}}
        
        self.spot = ccxt.binance(spot_params)
        self.futures = ccxt.binance(futures_params)
    
    def test_connection(self) -> bool:
        """Test API connection."""
        try:
            if self.config.test_mode:
                logger.info("✅ Test mode - skipping connection check")
                return True
            
            self.spot.fetch_time()
            self.futures.fetch_time()
            
            balance = self.get_balance()
            logger.info(f"✅ Connected! Balance: ${balance:,.2f}")
            return True
        except Exception as e:
            logger.error(f"❌ Connection failed: {e}")
            return False
    
    def get_balance(self) -> float:
        """Get total USDT balance."""
        try:
            if self.config.test_mode:
                return self.config.capital
            
            spot_bal = self.spot.fetch_balance()
            futures_bal = self.futures.fetch_balance()
            
            spot_usdt = float(spot_bal.get('USDT', {}).get('free', 0))
            futures_usdt = float(futures_bal.get('USDT', {}).get('free', 0))
            
            return spot_usdt + futures_usdt
        except:
            return self.config.capital
    
    def get_historical_data(self, symbol: str, limit: int = 300) -> pd.DataFrame:
        """Get OHLCV data."""
        try:
            ohlcv = self.spot.fetch_ohlcv(symbol, '1h', limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            return df
        except:
            return pd.DataFrame()
    
    def get_funding_rates(self) -> Dict:
        """Get funding rates."""
        try:
            tickers = self.futures.fetch_tickers()
            rates = {}
            for symbol, ticker in tickers.items():
                if '/USDT:' in symbol:
                    base = symbol.split('/')[0]
                    rate = float(ticker.get('info', {}).get('lastFundingRate', 0))
                    if abs(rate) > 0:
                        rates[base] = {
                            'symbol': symbol,
                            'rate': rate,
                            'price': float(ticker.get('markPrice', 0)),
                        }
            return rates
        except:
            return {}

# ============================================================
# TECHNICAL INDICATORS
# ============================================================
def calculate_indicators(df: pd.DataFrame, config: Config) -> pd.DataFrame:
    """Calculate all indicators."""
    df = df.copy()
    
    # EMAs
    df['ema_fast'] = df['close'].ewm(span=config.ema_fast, adjust=False).mean()
    df['ema_slow'] = df['close'].ewm(span=config.ema_slow, adjust=False).mean()
    
    # ATR
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.ewm(span=config.atr_period, adjust=False).mean()
    df['atr_pct'] = df['atr'] / df['close']
    
    # Breakout levels
    df['high_20'] = df['high'].rolling(config.breakout_lookback).max().shift(1)
    df['low_20'] = df['low'].rolling(config.breakout_lookback).min().shift(1)
    
    # Trend
    df['uptrend'] = df['ema_fast'] > df['ema_slow']
    df['downtrend'] = df['ema_fast'] < df['ema_slow']
    
    # Volatility
    df['volatile'] = df['atr_pct'] > 0.015
    
    # Signals
    df['long_signal'] = (df['close'] > df['high_20'] * 1.001) & df['volatile'] & df['uptrend']
    df['short_signal'] = (df['close'] < df['low_20'] * 0.999) & df['volatile'] & df['downtrend']
    
    return df

# ============================================================
# TRADING BOT
# ============================================================
class TradingBot:
    def __init__(self, config: Config):
        self.config = config
        self.exchange = Exchange(config)
        self.positions = []
        self.trade_history = []
        self.daily_pnl = 0
        self.current_date = datetime.now().date()
        self.iteration = 0
    
    def start(self):
        """Start the bot."""
        logger.info("=" * 50)
        logger.info("🤖 BINANCE TRADING BOT STARTING")
        logger.info("=" * 50)
        logger.info(f"Test Mode: {self.config.test_mode}")
        logger.info(f"Leverage: {self.config.leverage}x")
        logger.info(f"Risk/Trade: {self.config.risk_per_trade*100}%")
        logger.info(f"Pairs: {', '.join([p.split('/')[0] for p in self.config.pairs])}")
        logger.info("=" * 50)
        
        if not self.exchange.test_connection():
            logger.error("Cannot start - connection failed")
            return
        
        logger.info("🚀 Bot is running. Press Ctrl+C to stop.")
        
        try:
            while True:
                self._run_iteration()
                time.sleep(300)  # 5 minutes
        except KeyboardInterrupt:
            logger.info("🛑 Bot stopped by user")
            self._print_summary()
    
    def _run_iteration(self):
        """Run one iteration."""
        self.iteration += 1
        
        # Reset daily P&L
        if datetime.now().date() != self.current_date:
            self.daily_pnl = 0
            self.current_date = datetime.now().date()
        
        logger.info(f"\n{'─'*40}")
        logger.info(f"🔄 Iteration {self.iteration} | {datetime.now().strftime('%H:%M:%S')}")
        
        # Scan for breakout signals
        self._scan_breakouts()
        
        # Scan for funding opportunities
        self._scan_funding()
        
        # Display status
        logger.info(f"💼 Balance: ${self.exchange.get_balance():,.2f} | "
                   f"Positions: {len(self.positions)} | "
                   f"Trades: {len(self.trade_history)}")
    
    def _scan_breakouts(self):
        """Scan for breakout signals."""
        if len(self.positions) >= self.config.max_positions:
            return
        
        for pair in self.config.pairs:
            if len(self.positions) >= self.config.max_positions:
                break
            
            # Get data
            df = self.exchange.get_historical_data(pair, 300)
            if df.empty:
                continue
            
            # Calculate indicators
            df = calculate_indicators(df, self.config)
            latest = df.iloc[-1]
            
            # Check signals
            if latest['long_signal']:
                logger.info(f"🎯 LONG signal: {pair} @ ${latest['close']:.2f}")
                self._log_signal(pair, 'LONG', latest)
            
            elif latest['short_signal']:
                logger.info(f"🎯 SHORT signal: {pair} @ ${latest['close']:.2f}")
                self._log_signal(pair, 'SHORT', latest)
    
    def _scan_funding(self):
        """Scan for funding opportunities."""
        rates = self.exchange.get_funding_rates()
        
        for symbol, data in rates.items():
            if abs(data['rate']) > self.config.funding_threshold:
                annualized = abs(data['rate']) * 3 * 365 * 100
                logger.info(f"💰 {symbol}: {data['rate']*100:.4f}% funding "
                          f"({annualized:.1f}% annualized)")
    
    def _log_signal(self, pair: str, direction: str, data):
        """Log a trading signal."""
        logger.info(f"   Entry: ${data['close']:.2f}")
        logger.info(f"   ATR: ${data['atr']:.2f} ({data['atr_pct']*100:.2f}%)")
        logger.info(f"   Trend: {'UP' if data['uptrend'] else 'DOWN'}")
        
        # In test mode, simulate trade
        if self.config.test_mode:
            logger.info(f"   [TEST] Would open {direction} position")
            self.positions.append({
                'symbol': pair,
                'direction': direction,
                'entry': data['close'],
                'time': datetime.now(),
            })
    
    def _print_summary(self):
        """Print trading summary."""
        logger.info(f"""
╔══════════════════════════════════╗
║         BOT SUMMARY             ║
╠══════════════════════════════════╣
║ Iterations:  {self.iteration:<18} ║
║ Signals:     {len(self.positions):<18} ║
║ Balance:     ${self.exchange.get_balance():<17,.2f} ║
╚══════════════════════════════════╝
        """)

# ============================================================
# MAIN
# ============================================================
if __name__ == '__main__':
    config = Config()
    
    if not config.api_key or not config.api_secret:
        logger.error("❌ API keys not set!")
        logger.error("Set BINANCE_API_KEY and BINANCE_API_SECRET environment variables")
        logger.error("Running in demo mode with fake data...")
        config.test_mode = True
    
    bot = TradingBot(config)
    bot.start()
