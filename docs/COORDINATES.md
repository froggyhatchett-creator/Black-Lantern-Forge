# Coordinate System

| Property | Value |
|---|---|
| Handedness | Right-handed |
| Up axis | +Y |
| Units | Meters (all lengths, everywhere; no mixed units) |
| Sword axis | Blade tip points +Y; pommel toward −Y |
| Blade edges | ±X |
| Blade flats | Face ±Z |
| Origin | Center of the grip, on the sword's centerline |
| Winding | Counter-clockwise front faces seen from outside → outward normals |
| Symmetry | Every component is symmetric about the YZ and XY planes |

## Layout along Y (bottom to top)

```
 +Y  ▲   tip            y = G/2 + T + L
     │   blade          length L
     │   ─────────────  y = G/2 + T        (guard top = blade base)
     │   guard          thickness T
     │   ─────────────  y = G/2            (grip top = guard bottom)
     │   grip           length G
     ●   origin         y = 0              (grip center)
     │   ─────────────  y = −G/2           (grip bottom = pommel top)
     │   pommel         height H
     │                  y = −G/2 − H
```

Components touch at their interfaces (within 1 picometer of floating-point
error). They're separate closed shells, not welded.

## Mapping to engines (informational)

Forge doesn't integrate with any engine. For reference only:
Unreal is left-handed Z-up (centimeters); Unity is left-handed Y-up (meters).
Converting is the importer's job. Step 3 engine packages (glTF 2.0) use this
frame unchanged, which is glTF's native frame. See
[FORGE_ENGINE_CONTRACT_V1.md](FORGE_ENGINE_CONTRACT_V1.md) §5 and §16.
