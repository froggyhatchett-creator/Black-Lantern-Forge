"""Forge exception hierarchy.

Every error Forge raises on purpose derives from ForgeError, so callers can
catch Forge failures without catching unrelated bugs. Errors caused by bad
caller input also derive from ValueError.
"""


class ForgeError(Exception):
    """Base class for all intentional Forge failures."""


class InvalidSeedError(ForgeError, ValueError):
    """Seed is not an int in [0, 2**64 - 1] (or a CLI seed string failed to parse)."""


class UnsupportedGeneratorVersionError(ForgeError, ValueError):
    """Requested generator version is not registered."""


class GenerationError(ForgeError):
    """The generator produced output that violates its own contract.

    This signals a Forge bug, not bad input. It is never repaired silently.
    """


class GeometryError(ForgeError):
    """A mesh failed structural validation (bad index, non-finite value, degenerate face, open shell...)."""


class ExportError(ForgeError):
    """An exporter could not produce valid output."""


class EnvironmentNotSupportedError(ForgeError):
    """The Python float environment cannot honor Forge's determinism contract."""


# ---------------------------------------------------------------- Step 2

class UnsupportedVersionError(ForgeError, ValueError):
    """A presentation, normals, UV, material, preview, or record version is not registered."""


class PresentationError(ForgeError):
    """Derived presentation data (normals, UVs, materials) violates its contract. A Forge bug."""


class RecordFormatError(ForgeError, ValueError):
    """An asset record is malformed: bad JSON, missing/unknown fields, wrong types, bad values."""


class RecordIntegrityError(ForgeError):
    """An asset record parsed fine, but regenerating it did not reproduce what it claims."""


class RenderError(ForgeError):
    """The preview renderer was given invalid settings or produced invalid output."""


# ---------------------------------------------------------------- Step 2.5 (registries)

class RegistryError(ForgeError, ValueError):
    """A registry lookup failed: unknown identifier or unsupported version."""


class RegistryConfigurationError(ForgeError):
    """The registry tables themselves are inconsistent (duplicate key, dangling reference). A Forge bug."""


class UnknownAssetTypeError(RegistryError, RecordFormatError):
    """No asset type is registered under this identifier.

    Also a RecordFormatError, so code that catches malformed records (Step 2
    behavior for an unknown asset_type) keeps working.
    """


class UnknownGeneratorError(RegistryError, RecordFormatError):
    """No generator is registered under this identifier (or it does not produce the asset type).

    Also a RecordFormatError, for the same Step 2 compatibility reason.
    """


class UnknownPresentationError(RegistryError):
    """No presentation pipeline is registered under this identifier."""


class UnknownExportFormatError(RegistryError, ExportError):
    """No exporter is registered under this format identifier, or the asset type does not offer it."""


class UnsupportedExportVersionError(RegistryError, UnsupportedVersionError):
    """The export format is registered, but not at this version (or not for this asset type)."""


class UnknownPreviewError(RegistryError, RenderError):
    """No preview renderer is registered under this identifier, or the asset type has no preview."""


# ---------------------------------------------------------------- Step 3 (engine contract)

class EngineContractError(ForgeError, ValueError):
    """An engine package (GLB + manifest) does not conform to the Forge -> Engine Asset Contract.

    Raised by the independent package validator. Nothing is repaired: the first
    violation found is reported and validation stops.
    """
