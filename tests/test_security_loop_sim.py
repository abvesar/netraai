from __future__ import annotations

import unittest

from security_loop_sim import SecurityLoop, SecurityLoopConfig, SimulatedRelay


class SecurityLoopTests(unittest.TestCase):
    def test_relay_closes_only_when_both_signals_true(self) -> None:
        relay = SimulatedRelay()
        loop = SecurityLoop(
            relay=relay,
            config=SecurityLoopConfig(sobriety_ok=True, facial_ok=True, cycles=1),
        )
        allowed = loop.evaluate_once()
        self.assertTrue(allowed)
        self.assertTrue(relay.closed)

    def test_relay_stays_open_when_any_signal_false(self) -> None:
        relay = SimulatedRelay()
        loop = SecurityLoop(
            relay=relay,
            config=SecurityLoopConfig(sobriety_ok=True, facial_ok=False, cycles=1),
        )
        allowed = loop.evaluate_once()
        self.assertFalse(allowed)
        self.assertFalse(relay.closed)


if __name__ == "__main__":
    unittest.main()
