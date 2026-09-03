"""Application-specific exception hierarchy."""


class WeatherSimError(Exception):
    """Base class for errors users can act on."""


class ConfigurationError(WeatherSimError):
    """The experiment configuration is invalid."""


class ObservationDataError(WeatherSimError):
    """Observation data is absent or malformed."""


class WRFOutputError(WeatherSimError):
    """A WRF output file is absent, malformed, or unsupported."""


class ExternalCommandError(WeatherSimError):
    """WPS or WRF did not complete successfully."""
