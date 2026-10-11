"""Forge Engine Viewer (Step 4, FIRST INGESTION): an independent engine-side consumer of
Forge -> Engine Asset Contract v1 packages.

It reads a .forgepkg directory from disk, validates it (fail closed), decodes the GLB with its
own reader, and shows the render geometry, the declared sockets and the collision hull.
It imports nothing from the `forge` package: the dependency runs Forge -> package -> viewer.
"""

__version__ = "0.4.0"
