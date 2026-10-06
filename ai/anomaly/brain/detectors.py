"""Couches 2 et 4 : détecteurs en flux, une mesure à la fois, mémoire bornée (légers : PC serveur comme Raspberry Pi).

- RobustCusum : ligne de base EWMA, échelle robuste (MAD), CUSUM bilatéral. Couche 2.
- Holt        : lissage exponentiel double à pas de temps variable, prévision et eta. Couche 4.
- RateOfRise  : vitesse de montée (tendance de Holt) comparée à l'enveloppe du régime sain. Couche 2,
                principe des détecteurs thermovélocimétriques de l'incendie (alarme sur la vitesse, pas le niveau).
- PoissonRate : test de Poisson sur un taux d'événements (PIR par minute). Couche 2, domaine physique.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

import numpy as np

MAD_TO_SIGMA = 1.4826        # MAD -> écart-type pour une loi normale


@dataclass
class CusumOut:
    value: float
    baseline: float
    sigma: float
    z: float
    s_up: float
    s_down: float
    score: float              # 0 à 100 ; 60 = seuil de décision atteint
    alarm: bool
    direction: str            # "up", "down" ou ""


class RobustCusum:
    """CUSUM de Page (1954) sur des écarts robustes, avec gel de la ligne de base pendant une suspicion.

    z  = (x - µ) / σ        µ : EWMA lente des mesures saines   σ : 1,4826 × MAD des résidus (30 dernières min)
    S+ = max(0, S+ + w·(z - k))   S- = max(0, S- + w·(-z - k))     alarme quand S >= h
    w = dt / tau_d : les capteurs physiques sont très autocorrélés (le gaz « respire » sur ~90 s), deux mesures
    à 2 s d'écart ne sont pas deux preuves indépendantes. On compte donc une observation par tau_d secondes
    (décorrélation) ; c'est aussi ce qui rend le détecteur insensible au rythme d'envoi (rafales à 500 ms).
    k : moitié du plus petit décalage à détecter (en σ). h : réglé par la sensibilité du profil de site.
    k et h sont calibrés sur des heures de régime normal (taux de fausses alarmes visé), voir le notebook.
    """

    def __init__(self, name: str, *, h: float = 5.0, k: float = 1.5, tau_s: float = 600.0,
                 min_sigma: float = 0.01, ref_size: int = 900, warmup_s: float = 600.0,
                 tau_d: float = 30.0, direction: str = "both", cap: float = 1.5):
        self.name, self.h, self.k, self.tau_s = name, h, k, tau_s
        self.min_sigma, self.warmup_s, self.tau_d = min_sigma, warmup_s, tau_d
        self.direction, self.cap = direction, cap
        self.resid: deque[float] = deque(maxlen=ref_size)
        self.mu: float | None = None
        self.sigma = min_sigma
        self.s_up = self.s_down = 0.0
        self.t0: float | None = None
        self.last_t: float | None = None

    def _learn(self, x: float, a: float) -> None:
        self.mu += a * (x - self.mu)
        self.resid.append(x - self.mu)

    def update(self, x: float, t: float) -> CusumOut:
        if self.mu is None:
            self.mu, self.t0 = x, t
        dt = 2.0 if self.last_t is None else min(60.0, max(0.0, t - self.last_t))
        self.last_t = t
        if t - self.t0 < self.warmup_s:               # apprentissage : on apprend sans juger
            self._learn(x, max(0.05, 1.0 - math.exp(-dt / self.tau_s)))
            return CusumOut(x, self.mu, self.sigma, 0.0, 0.0, 0.0, 0.0, False, "")
        if len(self.resid) >= 10:
            r = np.fromiter(self.resid, float)
            self.sigma = max(self.min_sigma, MAD_TO_SIGMA * float(np.median(np.abs(r - np.median(r)))))
        z = (x - self.mu) / self.sigma
        w = dt / self.tau_d
        lim = self.cap * self.h                          # plafond : retour rapide au calme après l'anomalie
        if self.direction in ("both", "up"):
            self.s_up = min(lim, max(0.0, self.s_up + w * (z - self.k)))
        if self.direction in ("both", "down"):
            self.s_down = min(lim, max(0.0, self.s_down + w * (-z - self.k)))
        s = max(self.s_up, self.s_down)
        if s < self.h / 2:                             # gel : on n'apprend pas l'anomalie en cours
            self._learn(x, 1.0 - math.exp(-dt / self.tau_s))
        direction = "up" if self.s_up >= self.s_down and self.s_up > 0 else ("down" if self.s_down > 0 else "")
        # 60 au seuil de décision ; au-delà, le niveau seul plafonne à 70 : monter plus haut doit être justifié
        # par la vitesse, la prévision ou un seuil absolu (un reste de gaz après une fuite n'est pas une urgence)
        score = 60.0 * s / self.h if s <= self.h else 60.0 + 10.0 * (s - self.h) / ((self.cap - 1.0) * self.h)
        return CusumOut(x, self.mu, self.sigma, z, self.s_up, self.s_down, min(70.0, score), s >= self.h, direction)


class Holt:
    """Lissage exponentiel double (Holt, 1957) à pas de temps variable (rafales de 500 ms, coupures).

    niveau  L = a·x + (1-a)·(L + T·dt)        a = 1 - exp(-dt/tau_level)
    tendance T = b·(L - L_préc)/dt + (1-b)·T   b = 1 - exp(-dt/tau_trend)     (T en unités par seconde)
    """

    def __init__(self, tau_level: float = 10.0, tau_trend: float = 60.0):
        self.tl, self.tt = tau_level, tau_trend
        self.level: float | None = None
        self.trend = 0.0
        self.last_t: float | None = None

    def update(self, x: float, t: float) -> None:
        if self.level is None:
            self.level, self.last_t = x, t
            return
        dt = t - self.last_t
        if dt <= 0:                       # même seconde (rafale) : on lisse sans toucher à la tendance
            self.level += 0.3 * (x - self.level)
            return
        a = 1.0 - math.exp(-dt / self.tl)
        b = 1.0 - math.exp(-dt / self.tt)
        prev = self.level
        self.level = a * x + (1 - a) * (self.level + self.trend * dt)
        self.trend = b * (self.level - prev) / dt + (1 - b) * self.trend
        self.last_t = t

    def forecast(self, seconds: float) -> float:
        return (self.level or 0.0) + self.trend * seconds

    def eta_min(self, target: float, min_slope_per_min: float, horizon_min: float) -> float | None:
        """Minutes avant d'atteindre target si la tendance actuelle se maintient ; None si hors horizon."""
        if self.level is None:
            return None
        if self.level >= target:
            return 0.0
        slope = self.trend * 60.0
        if slope < min_slope_per_min:
            return None
        eta = (target - self.level) / slope
        return round(eta, 1) if eta <= horizon_min else None


class RateOfRise:
    """Alarme quand la grandeur monte plus vite que tout ce qui a été vu en régime sain.

    seuil = max(plancher, marge × plus forte montée saine observée)
    Le plancher vient de la calibration (24 h de régime normal) ; l'enveloppe apprise ne peut que le relever,
    jamais l'abaisser : un capteur réel plus bruité que le simulateur rendra Brain plus tolérant, pas plus nerveux.
    """

    def __init__(self, holt: Holt, *, floor_per_min: float, margin: float = 1.25, scale: float = 1.0,
                 memory: int = 8640, sample_s: float = 10.0):
        self.holt, self.floor, self.margin, self.scale = holt, floor_per_min, margin, scale
        self.healthy: deque[float] = deque(maxlen=memory)     # 24 h à une valeur toutes les 10 s
        self.sample_s = sample_s
        self.last_sample = -1e18
        self.peak = 0.0

    @property
    def rate(self) -> float:
        """Vitesse actuelle, par minute (× scale : 100 pour exprimer un ratio en %)."""
        return self.holt.trend * 60.0 * self.scale

    @property
    def threshold(self) -> float:
        return max(self.floor, self.margin * self.peak)

    def update(self, t: float, healthy: bool) -> tuple[float, bool]:
        """À appeler après holt.update. Renvoie (score 0..100, alarme)."""
        r = self.rate
        if healthy and t - self.last_sample >= self.sample_s:
            self.last_sample = t
            if len(self.healthy) == self.healthy.maxlen and self.healthy[0] >= self.peak:
                self.healthy.popleft()
                self.peak = max(self.healthy, default=0.0)
            self.healthy.append(r)
            self.peak = max(self.peak, r)
        score = min(100.0, max(0.0, 60.0 * r / self.threshold))
        return score, r >= self.threshold


class PoissonRate:
    """Taux d'événements (PIR) comparé au taux normal appris : probabilité d'en voir autant par hasard."""

    def __init__(self, min_rate: float = 0.1, tau_s: float = 1800.0):
        self.rate = min_rate              # événements par minute en régime normal
        self.min_rate, self.tau_s = min_rate, tau_s
        self.last_t: float | None = None

    @staticmethod
    def tail(n: int, lam: float) -> float:
        """P(N >= n) pour N ~ Poisson(lam)."""
        if n <= 0:
            return 1.0
        term = cdf = math.exp(-lam)
        for i in range(1, n):
            term *= lam / i
            cdf += term
        return max(1e-12, 1.0 - cdf)

    def update(self, count_per_min: int, t: float, learn: bool, p60: float = 1e-4) -> tuple[float, float]:
        """Renvoie (score 0..100, p). Score 60 quand p = p60 (1 chance sur 10 000 par défaut que ce soit du hasard)."""
        dt = 2.0 if self.last_t is None else max(0.0, t - self.last_t)
        self.last_t = t
        p = self.tail(int(count_per_min), self.rate)
        if learn:
            a = 1.0 - math.exp(-dt / self.tau_s)
            self.rate = max(self.min_rate, self.rate + a * (count_per_min - self.rate))
        return min(100.0, 60.0 * math.log10(p) / math.log10(p60)), p
