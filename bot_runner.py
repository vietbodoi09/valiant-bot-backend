"""
Bot Runner - Wrapper for Bot2 to work with backend session
"""
import asyncio
import logging
import sys
import os

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger("BotRunner")

class BotRunner:
    def __init__(self, config, session):
        self.config = config
        self.session = session
        self.is_running = False
        self.bot2 = None
        self._stop_event = asyncio.Event()
    
    async def _handle_bot_update(self, update_type: str, data: dict):
        """Handle updates from Bot2 and send to frontend via WebSocket"""
        try:
            if update_type == "balances":
                self.session.update_balances(data)
            elif update_type == "stats":
                self.session.update_stats(data)
            elif update_type == "position":
                # Handle position updates if needed
                pass
        except Exception as e:
            logger.error(f"Failed to handle bot update: {e}")
        
    async def run(self):
        """Main bot loop - wraps Bot2"""
        self.is_running = True
        mode = self.config.get('mode', 'hedge')
        cycles = self.config.get('cycles', 1)
        
        self.session.add_log(f"Bot started - {mode.upper()} mode")
        self.session.add_log(f"Config: {self.config}")
        
        try:
            # Import Bot2 from bot2.py
            from bot2 import Bot2, TradeConfig
            
            # Convert config dict to TradeConfig
            # Get cycles from web (default = 1 cycle)
            cycles = self.config.get('cycles', 1)
            auto_reenter = self.config.get('auto_reenter', True)
            
            # If auto_reenter is OFF, only run 1 cycle
            # If auto_reenter is ON, use cycles from web (-1 = infinite)
            hedge_cycles = cycles if (auto_reenter and cycles > 0) else (1 if not auto_reenter else -1)
            
            trade_config = TradeConfig(
                symbol=self.config.get('symbol', 'BTC'),
                size_usd=self.config.get('size_usd', 150.0),
                spam_leverage=self.config.get('leverage', 10),
                spam_interval_sec=self.config.get('spam_interval', 10.0),
                spam_rounds=self.config.get('spam_rounds', 10),
                hedge_leverage=self.config.get('leverage', 10),
                hedge_hold_hours=self.config.get('hedge_hold_hours', 8.0),
                hedge_auto_reenter=auto_reenter,
                hedge_cycles=hedge_cycles,
                hedge_rest_hours=0.5,
                hedge_exit_on_fee=True
            )
            
            self.session.add_log(f"Config: cycles={hedge_cycles}, auto_reenter={auto_reenter}, hold_hours={trade_config.hedge_hold_hours}h")
            
            # Create Bot2 instance with callback to send data to frontend
            self.bot2 = Bot2(trade_config, update_callback=self._handle_bot_update)
            
            # Override bot2's logger to send to session
            self._setup_logging_override()
            
            # Initialize Lighter connection
            await self.bot2.init_lighter()
            
            # Run the appropriate mode
            if mode == 'hedge':
                await self._run_hedge_mode()
            elif mode == 'spam':
                await self._run_spam_mode()
            else:
                self.session.add_log("Unknown mode, defaulting to hedge")
                await self._run_hedge_mode()
                
        except ImportError as e:
            logger.error(f"Failed to import bot2: {e}")
            self.session.add_log(f"ERROR: Cannot import bot2.py - {e}")
            # Fallback to simulation mode
            await self._run_simulation_mode()
        except asyncio.CancelledError:
            logger.info("Bot cancelled")
            self.session.add_log("Bot cancelled by user")
        except Exception as e:
            logger.error(f"Bot error: {e}")
            self.session.add_log(f"ERROR: {str(e)}")
            import traceback
            self.session.add_log(traceback.format_exc())
    
    def _setup_logging_override(self):
        """Override bot2's logging to send to session"""
        import logging
        
        class SessionLogHandler(logging.Handler):
            def __init__(self, session):
                super().__init__()
                self.session = session
            
            def emit(self, record):
                msg = self.format(record)
                self.session.add_log(msg)
        
        # Add handler to bot2 logger
        bot2_logger = logging.getLogger("Bot2")
        handler = SessionLogHandler(self.session)
        handler.setLevel(logging.INFO)
        bot2_logger.addHandler(handler)
    
    async def _run_hedge_mode(self):
        """Run hedge mode with cycle tracking"""
        self.session.add_log("Starting hedge mode...")
        
        # Check for stale positions
        has_stale = await self.bot2.safety_check_on_startup()
        if has_stale:
            self.session.add_log("WARNING: Stale positions found!")
        
        # Set leverage
        self.bot2.set_leverage()
        
        # Run cycles
        cycle_count = 0
        max_cycles = self.config.get('cycles', 1)
        
        while self.is_running and (max_cycles < 0 or cycle_count < max_cycles):
            cycle_count += 1
            self.session.add_log(f"=== CYCLE {cycle_count}/{max_cycles if max_cycles > 0 else '∞'} ===")
            
            # Run single cycle
            should_continue = await self.bot2._run_single_hedge_cycle()
            
            if not should_continue or not self.is_running:
                break
            
            # Rest before next cycle
            if self.bot2.config.hedge_auto_reenter:
                rest_hours = self.bot2.config.hedge_rest_hours
                self.session.add_log(f"Resting {rest_hours}h before next cycle...")
                await asyncio.sleep(rest_hours * 3600)
        
        self.session.add_log(f"Hedge mode completed. Total cycles: {cycle_count}")
        
        # Export report if available
        if self.bot2.cycle_reports:
            self.bot2._export_report()
    
    async def _run_spam_mode(self):
        """Run spam mode"""
        self.session.add_log("Starting spam mode...")
        await self.bot2.run_spam_mode()
        self.session.add_log("Spam mode completed")
    
    async def _run_simulation_mode(self):
        """Fallback simulation mode when bot2 is not available"""
        import random
        
        self.session.add_log("Running in SIMULATION mode (bot2.py not available)")
        
        symbol = self.config.get('symbol', 'BTC')
        size = self.config.get('size_usd', 150)
        leverage = self.config.get('leverage', 10)
        mode = self.config.get('mode', 'hedge')
        cycles = self.config.get('cycles', 1)
        
        if mode == 'hedge':
            # Simulate hedge mode with cycles
            for cycle in range(1, cycles + 1):
                if not self.is_running:
                    break
                    
                self.session.add_log(f"=== SIMULATION CYCLE {cycle}/{cycles} ===")
                
                # Simulate opening positions
                self.session.update_position("hyperliquid", {
                    "symbol": f"{symbol}-USD",
                    "side": "long",
                    "size": size,
                    "entry_price": 45000.0,
                    "mark_price": 45000.0,
                    "pnl": 0.0,
                    "pnl_percent": 0.0,
                    "exchange": "hyperliquid",
                    "leverage": leverage
                })
                self.session.add_log(f"[HyperLiquid] LONG {size}$ {symbol} @ 45000")
                
                self.session.update_position("lighter", {
                    "symbol": f"{symbol}-USD",
                    "side": "short",
                    "size": size,
                    "entry_price": 45000.0,
                    "mark_price": 45000.0,
                    "pnl": 0.0,
                    "pnl_percent": 0.0,
                    "exchange": "lighter",
                    "leverage": leverage
                })
                self.session.add_log(f"[Lighter] SHORT {size}$ {symbol} @ 45000")
                
                self.session.update_stats({
                    "total_trades": cycle * 2,
                    "total_volume": size * 2 * cycle,
                    "total_pnl": random.uniform(-5, 5)
                })
                
                # Simulate hold time
                hold_seconds = min(10, self.config.get('hedge_hold_hours', 8) * 3600)
                self.session.add_log(f"Holding for {hold_seconds}s (simulated)...")
                
                for i in range(int(hold_seconds / 2)):
                    if not self.is_running:
                        break
                    await asyncio.sleep(2)
                    
                    # Update prices
                    price_change = random.uniform(-50, 50)
                    new_price = 45000.0 + price_change
                    
                    for exchange in ["hyperliquid", "lighter"]:
                        pos = {"symbol": f"{symbol}-USD", "side": "long" if exchange == "hyperliquid" else "short",
                               "size": size, "entry_price": 45000.0, "mark_price": new_price,
                               "pnl": (new_price - 45000.0) * size / 45000.0 * (1 if exchange == "hyperliquid" else -1),
                               "pnl_percent": ((new_price - 45000.0) / 45000.0 * 100) * (1 if exchange == "hyperliquid" else -1),
                               "exchange": exchange, "leverage": leverage}
                        self.session.update_position(exchange, pos)
                
                # Close positions
                self.session.add_log("Closing positions...")
                self.session.update_position("hyperliquid", None)
                self.session.update_position("lighter", None)
                
                if cycle < cycles and self.is_running and self.config.get('auto_reenter', True):
                    rest_sec = 2  # Short rest for simulation
                    self.session.add_log(f"Resting {rest_sec}s...")
                    await asyncio.sleep(rest_sec)
                    
        elif mode == 'spam':
            rounds = self.config.get('spam_rounds', 10)
            for i in range(rounds):
                if not self.is_running:
                    break
                self.session.add_log(f"Spam round {i+1}/{rounds}")
                self.session.update_stats({
                    "total_trades": i + 1,
                    "total_volume": (i + 1) * size,
                    "total_pnl": random.uniform(-10, 10)
                })
                await asyncio.sleep(self.config.get('spam_interval', 10))
        
        self.session.add_log("Simulation completed")
    
    async def stop(self):
        """Stop bot and close positions"""
        self.is_running = False
        self.session.add_log("Stopping bot...")
        
        if self.bot2:
            self.bot2.mode = "off"
            try:
                # Close all positions
                self.bot2.hl.close_position()
                if self.bot2.lighter.connected:
                    await self.bot2.lighter.close_position()
            except Exception as e:
                logger.error(f"Error closing positions: {e}")
        
        self.session.update_position("hyperliquid", None)
        self.session.update_position("lighter", None)
        self.session.add_log("Bot stopped")