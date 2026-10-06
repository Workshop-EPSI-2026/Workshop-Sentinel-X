"""Couche 3 : détection multivariée par Isolation Forest sur fenêtres glissantes de 60 s.

Elle repère des combinaisons inhabituelles même quand chaque capteur, pris seul, paraît normal
(ex. humidité qui baisse pendant que la température monte doucement). Apprentissage non supervisé,
uniquement sur des fenêtres sans incident, réentraîné périodiquement pour suivre le jour, la nuit, le chauffage.
"""
from __future__ import annotations

from collections import deque

import numpy as np
from sklearn.ensemble import IsolationForest

FEATURES = ["temp_mean", "temp_slope", "hum_mean", "hum_slope", "gas_mean", "gas_slope", "gas_std",
            "corr_temp_gas", "pir_per_min"]


def _slope_per_min(t: np.ndarray, y: np.ndarray) -> float:
    if len(t) < 3 or np.ptp(t) == 0:
        return 0.0
    tc = t - t.mean()
    return float(np.dot(tc, y - y.mean()) / np.dot(tc, tc)) * 60.0


def window_features(win: deque) -> dict[str, float] | None:
    """win : (t, temp lissée, humidité, ratio gaz, pir_count) des 60 dernières secondes."""
    if len(win) < 10:
        return None
    a = np.asarray(win, dtype=float)
    t, temp, hum, gas, pir = a.T
    corr = 0.0
    if temp.std() > 1e-6 and gas.std() > 1e-6:
        corr = float(np.corrcoef(temp, gas)[0, 1])
    return {"temp_mean": float(temp.mean()), "temp_slope": _slope_per_min(t, temp),
            "hum_mean": float(hum.mean()), "hum_slope": _slope_per_min(t, hum),
            "gas_mean": float(gas.mean()), "gas_slope": _slope_per_min(t, gas), "gas_std": float(gas.std()),
            "corr_temp_gas": corr, "pir_per_min": float(pir.max())}


class MultivariateDetector:
    def __init__(self, *, min_train: int = 90, max_train: int = 2000, retrain_every: int = 180,
                 persistence: int = 6, seed: int = 42):
        self.min_train = min_train          # fenêtres saines avant le premier modèle (15 min à 1 fenêtre / 10 s)
        self.retrain_every = retrain_every  # nouvelles fenêtres saines entre deux réentraînements (30 min)
        self.persistence = persistence      # fenêtres anormales consécutives (1 min) avant de lever le score
        self.train: deque[list[float]] = deque(maxlen=max_train)
        self.seed = seed
        self.model: IsolationForest | None = None
        self.ref_med = self.ref_q = 0.0
        self.new_since_fit = 0
        self.streak = 0
        self.fits = 0

    def fit(self) -> None:
        x = np.asarray(self.train)
        self.model = IsolationForest(n_estimators=100, max_samples=min(256, len(x)), contamination="auto",
                                     random_state=self.seed).fit(x)
        s = -self.model.score_samples(x)               # plus c'est haut, plus c'est anormal
        self.ref_med, self.ref_q = float(np.median(s)), float(np.quantile(s, 0.995))
        self.new_since_fit = 0
        self.fits += 1

    def score(self, feats: dict[str, float]) -> tuple[float, float]:
        """Renvoie (score 0..100 après persistance, score brut). 40 = rare (quantile 99,5 % du normal).
        Sans persistance, la contribution est plafonnée à 30 : une fenêtre isolée ne fait pas monter le score."""
        if self.model is None:
            return 0.0, 0.0
        s = -self.model.score_samples(np.asarray([[feats[k] for k in FEATURES]]))[0]
        raw = min(100.0, max(0.0, 40.0 * (s - self.ref_med) / max(1e-9, self.ref_q - self.ref_med)))
        self.streak = self.streak + 1 if raw >= 60 else 0
        return (raw if self.streak >= self.persistence else min(raw, 30.0)), raw

    def learn(self, feats: dict[str, float]) -> None:
        """À n'appeler que sur une fenêtre saine (aucun incident, score environnement bas)."""
        self.train.append([feats[k] for k in FEATURES])
        self.new_since_fit += 1
        if (self.model is None and len(self.train) >= self.min_train) or \
           (self.model is not None and self.new_since_fit >= self.retrain_every):
            self.fit()
