"""
ChronosEngine - Stochastic Mid-Price Generator.
Implements standard continuous Geometric Brownian Motion (GBM):
  dS_t = S_t * (mu * dt + sigma * dW_t)
Produces smooth, organic, high-frequency reference price trajectories with
realistic candle formations (wicks, bodies) without artificial bounds or hard clipping.
"""

import math
import random
from typing import Optional
from core.models.types import to_fixed_point


class JumpDiffusionPriceModel:
    """
    Continuous Geometric Brownian Motion (GBM) Mid-Price Simulator:
      dS_t = S_t * (mu * dt + sigma * dW_t)
    Exact discrete log-normal stepping:
      S_{t+1} = S_t * exp((mu - 0.5 * sigma^2) * dt + sigma * sqrt(dt) * Z)
      where Z ~ N(0, 1)

    Smooth continuous pricing:
      mu = 0.0 (no exaggerated trend drift)
      dt = 0.1 (100 ms discrete timestep)
      sigma = 0.0008 (smooth fluctuations: ~5 to 30 USDT per second at ~65,000 USDT)
    No artificial hard clipping (np.clip / min_price / max_price) is used.
    """

    def __init__(
        self,
        initial_price: float = 65000.0,
        drift: float = 0.0,
        volatility: float = 0.0008,
        dt: float = 0.1,
        mu: Optional[float] = None,
        sigma: Optional[float] = None,
        seed: Optional[int] = None,
        **kwargs,
    ) -> None:
        self.initial_price: float = float(initial_price)
        self.current_price: float = float(initial_price)
        self.drift: float = float(mu if mu is not None else drift)
        self.volatility: float = float(sigma if sigma is not None else volatility)
        self.dt: float = float(dt)

        if seed is not None:
            random.seed(seed)

    @property
    def mu(self) -> float:
        return self.drift

    @property
    def sigma(self) -> float:
        return self.volatility

    def next_price(self) -> float:
        """
        Computes the next continuous Geometric Brownian Motion price step:
          dS = S * (mu * dt + sigma * dW)
          S_{t+1} = S_t * exp((mu - 0.5 * sigma^2) * dt + sigma * sqrt(dt) * Z)
        """
        z = random.gauss(0.0, 1.0)
        drift_term = (self.drift - 0.5 * (self.volatility ** 2)) * self.dt
        diffusion_term = self.volatility * math.sqrt(self.dt) * z

        # Continuous organic update (strictly positive, no hard bounds)
        self.current_price = round(self.current_price * math.exp(drift_term + diffusion_term), 2)
        return self.current_price

    def get_fixed_price(self) -> int:
        """Returns the current mid-price as an integer in fixed-point (10^8 scale)."""
        return to_fixed_point(str(round(self.current_price, 2)))

    def reset(self) -> None:
        """Resets the model to initial price."""
        self.current_price = self.initial_price
