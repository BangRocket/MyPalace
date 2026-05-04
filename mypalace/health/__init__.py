"""Deep health + boot-time config validation (phase 8 slice 1)."""

from mypalace.health.checks import HealthCheckResult, check_all_backends
from mypalace.health.config_validator import ConfigError, validate_config

__all__ = [
    "ConfigError",
    "HealthCheckResult",
    "check_all_backends",
    "validate_config",
]
