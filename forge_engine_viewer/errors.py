"""The viewer's single error type. Ordinary bad input raises IngestionError and never crashes the viewer."""

from __future__ import annotations


class IngestionError(Exception):
    """A package was refused. `code` is a stable identifier; `message` says what is wrong, in plain words.

    Codes: not_a_package, missing_manifest, missing_glb, unexpected_entry, bad_manifest,
    unsupported_contract, hash_mismatch, malformed_glb, unsupported_feature, unsupported_accessor,
    bad_accessor, missing_attribute, bad_mesh, bad_material, bad_scene, bad_node, bad_transform,
    missing_socket, missing_collision, bad_collision, bad_coordinates, bad_lod, identity_mismatch,
    unreadable (an OS error while reading), malformed_package (structure this viewer did not anticipate:
    refused rather than guessed around).
    """

    def __init__(self, code: str, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


def refuse(code: str, message: str):
    raise IngestionError(code, message)


def require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise IngestionError(code, message)
