"""Réglages de Sentinel Brain, lus dans le profil de site (config/site.example.yml)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BrainConfig:
    # garde-fous absolus (section thresholds du profil)
    gas_warning: float = 1.3
    gas_critical: float = 1.8
    temp_warning: float = 35.0
    temp_critical: float = 45.0
    # sensibilités 0 (tolérant) .. 1 (très sensible) (section brain.sensitivity)
    sens_environment: float = 0.6
    sens_physical: float = 0.7
    sens_cyber: float = 0.8
    # fenêtres et délais (section brain)
    window_s: float = 60.0
    horizon_min: float = 10.0
    cooldown_s: float = 60.0
    retrain_every_min: float = 30.0
    learning_s: float = 600.0
    # apprentissage propre à chaque boîtier (devices.<id>.learning_minutes du profil)
    learning_by_device: tuple[tuple[str, float], ...] = ()

    def learning_for(self, device: str | None) -> float:
        return dict(self.learning_by_device).get(device or "", self.learning_s)

    @classmethod
    def from_profile(cls, profile: dict, device: str | None = None) -> BrainConfig:
        """Construit la configuration depuis le profil de site déjà chargé (dict YAML)."""
        th = profile.get("thresholds", {})
        br = profile.get("brain", {})
        sens = br.get("sensitivity", {})
        dev = (profile.get("devices") or {}).get(device or "", {})
        d = cls()
        return cls(
            gas_warning=th.get("gas_ratio", {}).get("warning", d.gas_warning),
            gas_critical=th.get("gas_ratio", {}).get("critical", d.gas_critical),
            temp_warning=th.get("temp_c", {}).get("warning", d.temp_warning),
            temp_critical=th.get("temp_c", {}).get("critical", d.temp_critical),
            sens_environment=sens.get("environment", d.sens_environment),
            sens_physical=sens.get("physical", d.sens_physical),
            sens_cyber=sens.get("cyber", d.sens_cyber),
            window_s=br.get("window_s", d.window_s),
            horizon_min=br.get("forecast_horizon_min", d.horizon_min),
            cooldown_s=br.get("cooldown_s", d.cooldown_s),
            retrain_every_min=br.get("retrain_every_min", d.retrain_every_min),
            learning_s=60.0 * dev.get("learning_minutes", d.learning_s / 60.0),
            learning_by_device=tuple((k, 60.0 * float(v.get("learning_minutes", d.learning_s / 60.0)))
                                     for k, v in (profile.get("devices") or {}).items() if isinstance(v, dict)),
        )

    @staticmethod
    def h_scale(sensitivity: float) -> float:
        """Multiplie le seuil h du CUSUM : 1,0 à la sensibilité 0,6 (point de calibration), 0,6 à 1, 1,6 à 0."""
        return 1.6 - min(1.0, max(0.0, sensitivity))

    @staticmethod
    def rate_margin(sensitivity: float) -> float:
        """Marge au-dessus de la plus forte montée saine : 1,25 à 0,6 ; 1,05 à 1 ; 1,55 à 0."""
        return 1.25 + 0.5 * (0.6 - min(1.0, max(0.0, sensitivity)))


# Réglages calibrés sur 24 h de régime normal simulé (graine 7), puis évalués sur un AUTRE jeu (graine 42) :
# voir ai/anomaly/notebooks/01-prototype.ipynb, section « Calibration ». À recalibrer sur données réelles
# (tâche « Données réelles ») avec la même cellule du notebook.
CALIBRATION = {
    #            CUSUM de niveau                                           vitesse de montée (Holt)
    "gas_ratio": {"k": 1.5, "h": 6.0, "tau_d": 60.0, "min_sigma": 0.02, "rate_floor": 10.0, "tau_trend": 30.0},
    "temp_c":    {"k": 1.5, "h": 5.0, "tau_d": 60.0, "min_sigma": 0.5, "rate_floor": 0.75, "tau_trend": 60.0},
    "hum_pct":   {"k": 2.0, "h": 5.0, "tau_d": 30.0, "min_sigma": 1.0},
    "rssi":      {"k": 2.0, "h": 3.0, "tau_d": 30.0, "min_sigma": 2.0},
}
