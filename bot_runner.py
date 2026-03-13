"""
Bot Runner - Wrapper for bot2.py to integrate with FastAPI backend
"""
import os
import sys
import asyncio
import logging
import time
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger("BotRunner")

class BotRunner:
    """Wrapper for Bot2 that integrates with backend"""
    
    def __init__(self, config: dict, manager):
        self.config = config
        self.manager = manager
        self.bot2 = None
        self.is_running = False
        self.bot_task = None
        
    async def run(self):
        """Main bot loop"""
        self.is_running = True
        
        try:
            # Import bot2 module
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from bot2 import Bot2, TradeConfig
            
            self.manager.add_log("Initializing Bot2...")
            
            # Debug: Check env vars
            lighter_keys_env = os.environ.get("LIGHTER_API_PRIVATE_KEYS", "NOT SET")
            lighter_account_env = os.environ.get("LIGHTER_ACCOUNT_INDEX", "NOT SET")
            self.manager.add_log(f"Env LIGHTER_ACCOUNT_INDEX: {lighter_account_env}")
            self.manager.add_log(f"Env LIGHTER_API_PRIVATE_KEYS length: {len(lighter_keys_env)}")
            self.manager.add_log(f"Env LIGHTER_API_PRIVATE_KEYS preview: {lighter_keys_env[:50]}..." if len(lighter_keys_env) > 50 else f"Env LIGHTER_API_PRIVATE_KEYS: {lighter_keys_env}")
            
            # Create TradeConfig from our config
            trade_config = TradeConfig(
                symbol=self.config.get("symbol", "BTC"),
                size_usd=self.config.get("size_usd", 150.0),
                spam_leverage=self.config.get("leverage", 10),
                hedge_leverage=self.config.get("leverage", 10),
                spam_interval_sec=self.config.get("spam_interval", 10.0),
                spam_rounds=self.config.get("spam_rounds", 10),
                spam_size_range=(100.0, 400.0),
                hedge_hold_hours=self.config.get("hedge_hold_hours", 8.0),
                hedge_auto_reenter=self.config.get("auto_reenter", True),
                hedge_cycles=-1 if self.config.get("auto_reenter", True) else 1,
                hedge_rest_hours=0.5,
                hedge_exit_on_fee=True,
            )
            
            # Create Bot2 instance
            self.bot2 = Bot2(trade_config)
            
            # Initialize Lighter connection
            self.manager.add_log("Connecting to Lighter...")
            await self.bot2.init_lighter()
            
            # Safety check
            self.manager.add_log("Running safety check...")
            has_stale = await self.bot2.safety_check_on_startup()
            
            if has_stale:
                self.manager.add_log("⚠️ Stale positions found! Please close manually before starting.")
                self.is_running = False
                return
            
            # Run based on mode
            mode = self.config.get("mode", "hedge")
            
            if mode == "spam":
                self.manager.add_log(f"Starting SPAM mode: {trade_config.spam_rounds} rounds")
                await self._run_spam_mode()
            else:
                self.manager.add_log(f"Starting HEDGE mode: {trade_config.hedge_hold_hours}h hold time")
                await self._run_hedge_mode()
                
        except Exception as e:
            logger.error(f"Bot error: {e}")
            self.manager.add_log(f"ERROR: {str(e)}")
            import traceback
            self.manager.add_log(traceback.format_exc())
        finally:
            self.is_running = False
            self.manager.add_log("Bot stopped")
    
    async def _run_spam_mode(self):
        """Run spam volume mode"""
        import random
        
        config = self.bot2.config
        symbol = config.symbol
        size_range = config.spam_size_range
        interval = config.spam_interval_sec
        rounds = config.spam_rounds
        
        self.bot2.mode = "spam"
        self.bot2.set_leverage(config.spam_leverage)
        
        self.manager.add_log(f"SPAM MODE: {rounds} rounds, {interval}s interval")
        
        for i in range(rounds):
            if not self.is_running or self.bot2.mode != "spam":
                break
            
            size_usd = random.uniform(*size_range)
            size_usd = round(size_usd, 2)
            side = "long" if i % 2 == 0 else "short"
            
            self.manager.add_log(f"Round {i+1}/{rounds}: {side.upper()} ${size_usd:.2f}")
            
            try:
                # Open position
                result = self.bot2.hl.market_order(side, size_usd)
                
                if result.get("error"):
                    self.manager.add_log(f"Order failed: {result['error']}")
                    await asyncio.sleep(5)
                    continue
                
                # Update stats
                self.manager.stats["total_trades"] += 1
                self.manager.stats["total_volume"] += size_usd
                self.manager.update_stats(self.manager.stats)
                
                # Update position display
                await self._update_positions()
                
                # Wait and close
                await asyncio.sleep(2)
                
                # Try close multiple times
                for attempt in range(3):
                    close_result = self.bot2.hl.close_position()
                    if not close_result.get("error"):
                        self.manager.add_log("Position closed")
                        break
                    self.manager.add_log(f"Close attempt {attempt+1} failed, retrying...")
                    await asyncio.sleep(2)
                
            except Exception as e:
                self.manager.add_log(f"Trade error: {e}")
            
            # Wait for next round
            if i < rounds - 1 and self.is_running and self.bot2.mode == "spam":
                await asyncio.sleep(interval)
        
        self.manager.add_log("Spam mode completed")
        self.bot2.mode = "off"
    
    async def _run_hedge_mode(self):
        """Run delta hedge mode"""
        config = self.bot2.config
        symbol = config.symbol
        size_usd = config.size_usd
        leverage = config.hedge_leverage
        hold_hours = config.hedge_hold_hours
        auto_reenter = config.hedge_auto_reenter
        
        self.bot2.mode = "hedge"
        cycle_count = 0
        
        self.manager.add_log(f"HEDGE MODE: {size_usd}$ @ {leverage}x, hold {hold_hours}h")
        self.manager.add_log(f"Lighter: {'Connected' if self.bot2.lighter.connected else 'Not connected'}")
        
        while self.is_running and self.bot2.mode == "hedge":
            cycle_count += 1
            self.manager.add_log(f"=== Cycle #{cycle_count} ===")
            
            try:
                # Get funding rates
                hl_funding = self.bot2.hl.get_funding_rate()
                lighter_funding = await self.bot2.lighter.get_funding_rate()
                
                self.manager.add_log(f"HL Funding: {hl_funding*100:.4f}%")
                self.manager.add_log(f"Lighter Funding: {lighter_funding*100:.4f}%")
                
                # Determine sides
                if hl_funding < lighter_funding:
                    hl_side = "long"
                    lighter_side = "short"
                    self.manager.add_log("Strategy: LONG HL + SHORT Lighter")
                else:
                    hl_side = "short"
                    lighter_side = "long"
                    self.manager.add_log("Strategy: SHORT HL + LONG Lighter")
                
                # Set leverage
                self.bot2.set_leverage(leverage)
                
                # Perfect delta entry
                if self.bot2.lighter.connected:
                    entry_success = await self.bot2.perfect_delta_entry(
                        hl_side, lighter_side, size_usd
                    )
                    if not entry_success:
                        self.manager.add_log("Entry failed, retrying in 60s...")
                        await asyncio.sleep(60)
                        continue
                else:
                    # HL only mode
                    self.manager.add_log("HL-only mode: Opening position...")
                    hl_order = self.bot2.hl.maker_open(hl_side, size_usd)
                    if hl_order.get("error"):
                        self.manager.add_log(f"HL entry failed: {hl_order['error']}")
                        await asyncio.sleep(60)
                        continue
                
                # Update stats
                self.manager.stats["total_trades"] += 1
                self.manager.stats["total_volume"] += size_usd * 2
                self.manager.update_stats(self.manager.stats)
                
                # Update positions
                await self._update_positions()
                
                # Monitor during hold time
                hold_seconds = hold_hours * 3600
                check_interval = 60  # Check every minute
                elapsed = 0
                
                while elapsed < hold_seconds and self.is_running and self.bot2.mode == "hedge":
                    await asyncio.sleep(check_interval)
                    elapsed += check_interval
                    
                    # Update positions
                    await self._update_positions()
                    
                    # Get HL position for PnL
                    hl_pos = self.bot2.hl.get_position()
                    if hl_pos:
                        pnl = float(hl_pos.get("unrealized_pnl") or 0)
                        progress = (elapsed / hold_seconds) * 100
                        self.manager.add_log(f"[{progress:.0f}%] PnL: ${pnl:.3f}")
                
                if not self.is_running or self.bot2.mode != "hedge":
                    break
                
                # Close positions
                self.manager.add_log("Closing positions...")
                await self._close_hedge()
                
                # Rest before next cycle
                if auto_reenter and self.is_running:
                    rest_minutes = 30
                    self.manager.add_log(f"Resting {rest_minutes}min before next cycle...")
                    await asyncio.sleep(rest_minutes * 60)
                else:
                    break
                    
            except Exception as e:
                self.manager.add_log(f"Cycle error: {e}")
                await asyncio.sleep(60)
        
        self.bot2.mode = "off"
        self.manager.add_log("Hedge mode completed")
    
    async def _close_hedge(self):
        """Close hedge positions - use market orders for guaranteed close"""
        try:
            self.manager.add_log("Closing all positions...")
            
            # HL close - use market_close for guaranteed fill
            hl_pos = self.bot2.hl.get_position()
            if hl_pos and abs(float(hl_pos.get("size", 0))) > 0.00001:
                self.manager.add_log(f"Closing HL position: {hl_pos.get('size')} BTC")
                hl_close = self.bot2.hl.close_position()  # market close
                self.manager.add_log(f"HL closed: {'OK' if not hl_close.get('error') else hl_close.get('error')}")
            else:
                self.manager.add_log("No HL position to close")
            
            # Lighter close
            if self.bot2.lighter.connected:
                lighter_pos = await self.bot2.lighter.get_position()
                if lighter_pos and lighter_pos.get("size", 0) > 0.00001:
                    await asyncio.sleep(15)  # Rate limit
                    lighter_close = await self.bot2.lighter.close_position()
                    self.manager.add_log(f"Lighter closed: {lighter_close.get('status', 'unknown')}")
                else:
                    self.manager.add_log("No Lighter position to close")
            
            # Verify HL closed
            await asyncio.sleep(1)
            hl_pos = self.bot2.hl.get_position()
            if hl_pos and abs(float(hl_pos.get("size") or 0)) > 0.00001:
                self.manager.add_log("HL still open, force closing...")
                self.bot2.hl.close_position()
            
            # Clear cached position
            self.bot2.lighter.last_position = None
            
            await self._update_positions()
            self.manager.add_log("All positions closed")
            
        except Exception as e:
            self.manager.add_log(f"Close error: {e}")
    
    async def _update_positions(self):
        """Update and broadcast position data"""
        try:
            # HL position
            hl_pos = self.bot2.hl.get_position()
            if hl_pos:
                position_data = {
                    "symbol": hl_pos.get("symbol", "BTC"),
                    "side": "long" if float(hl_pos.get("size", 0)) > 0 else "short",
                    "size": abs(float(hl_pos.get("size", 0))),
                    "entry_price": float(hl_pos.get("entry_price", 0)),
                    "mark_price": self.bot2.hl.exchange.get_mid_price(hl_pos.get("symbol", "BTC")) or float(hl_pos.get("entry_price", 0)),
                    "pnl": float(hl_pos.get("unrealized_pnl", 0)),
                    "liquidation_price": float(hl_pos.get("liquidation_price", 0)) if hl_pos.get("liquidation_price") else None,
                }
                self.manager.update_position("hyperliquid", position_data)
            else:
                self.manager.update_position("hyperliquid", None)
            
            # Lighter position
            if self.bot2.lighter.connected:
                lighter_pos = await self.bot2.lighter.get_position()
                if lighter_pos and lighter_pos.get("size", 0) > 0:
                    self.manager.update_position("lighter", {
                        "symbol": self.config.get("symbol", "BTC"),
                        "side": lighter_pos.get("side", "long"),
                        "size": float(lighter_pos.get("size", 0)),
                        "entry_price": float(lighter_pos.get("entry_price", 0)),
                        "mark_price": await self.bot2.lighter.trader.get_mid_price() or float(lighter_pos.get("entry_price", 0)),
                        "pnl": float(lighter_pos.get("unrealized_pnl", 0)),
                        "liquidation_price": float(lighter_pos.get("liquidation_price", 0)) if lighter_pos.get("liquidation_price") else None,
                    })
                else:
                    self.manager.update_position("lighter", None)
            
        except Exception as e:
            logger.error(f"Failed to update positions: {e}")
    
    async def stop(self):
        """Stop the bot and close positions"""
        self.is_running = False
        
        if self.bot2:
            self.bot2.mode = "off"
            
            self.manager.add_log("Stopping bot...")
            
            try:
                # Close positions
                await self._close_hedge()
                # Clear positions in UI
                self.manager.update_position("hyperliquid", None)
                self.manager.update_position("lighter", None)
                self.manager.add_log("All positions closed")
            except Exception as e:
                self.manager.add_log(f"Error closing positions: {e}")
