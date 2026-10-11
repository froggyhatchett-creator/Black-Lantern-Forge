"""Forge -> Engine Asset Contract (Step 3).

  contract   the versioned contract definition: names, required values, manifest schema, hash coverage
  glb        a direct, byte-stable GLB (binary glTF 2.0) writer; standard library only
  hull       an exact-integer convex hull for collision_hull
  package    build + write a package (asset.glb + manifest.json) from a frozen asset and presentation
  validate   the independent validator: its own GLB parser, fail closed, no generator needed

Generic code reaches the writer only through the export registry (format "glb", version 1,
registered in forge/catalog.py). Importing this package registers nothing.
"""
