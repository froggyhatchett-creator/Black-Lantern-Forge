# Human foundation assessment: improve the current mesh (A) or adopt a licensed base mesh (B)

Status: **for review**. No mesh has been replaced and no large implementation has started.

## 1. Can the current mesh reach the target?

Measured on the current template (generator v2):

| Fact | Value | Consequence |
|---|---|---|
| Vertices / triangles | 62,550 / 125,104 | Not a budget problem |
| Head region | 24,203 vertices (39%), uniform 2.7 mm edges | Density is ample, but spread evenly over the scalp, ears and neck as well as the features |
| Upper lid (tagged) | 19 vertices | No lid margin, no lid thickness, no crease, no lash line |
| Topology | Surface nets on an SDF: 36% of vertices irregular, 63% of triangles touch one | No edge loops around the eyes or mouth |
| Blink morph | Lids move at most 7.7 mm; eyes stay open | The lid is fused into the face surface, so there are no loops to slide over the eye |
| UVs | Automatic cylindrical layout | Not suitable for authored skin, pore or makeup textures |
| Face shape model | About 30 smooth-CSG ellipsoids, capsules and cones | Every feature looks like a blob, which reads as uncanny (see `phase2/F_lods.png` and `humanity/p1_eyes/`) |

**Conclusion.** The limiting factor is **topology and feature construction, not resolution**. Eyelids that close, mouth corners
that deform cleanly, lip edges, nostrils, the lid crease and the tear line all depend on edge loops placed by hand. A uniform
surface-nets mesh cannot provide those loops, however finely it is sampled. Shading work (P1 eyes) hit this ceiling: the
remaining eye defects are geometric.

## 2. The options

### A. Improve the current geometry and deformation system
- **A1, feature-aware remeshing.** Keep the SDF and add constrained loops around the eyes and mouth (remesh those regions
  with prescribed loops snapped to the field). Algorithmically hard and fragile across 53 parameters. Uncertain result;
  likely still blobby forms, because the SDF primitives themselves are the shape model.
- **A2, procedural head topology.** Generate a quad head from code (loops placed parametrically) and project it onto the
  SDF. This amounts to hand-building a head base mesh in code, which is very high effort, and the shape vocabulary stays
  ellipsoid-based.
- **Visual potential:** moderate at best. **Effort:** high to very high. **Compute:** every iteration needs a
  template rebuild plus a full studio bake (about 31 min on 4 workers).

### B. A licensed human base mesh as generator v3 (v1/v2 kept)
Candidates. Licence statements are from my knowledge and must be **verified against the licence files at download time**:

| Candidate | What it offers | Licence (to verify) | Fit |
|---|---|---|---|
| **MakeHuman / MPFB2 assets** (hm08 base mesh) | About 13k-vertex quad mesh with eye and mouth loops; separate eyes, teeth and tongue; about 1,000 morph targets (gender, age, muscle, weight, height, proportions, face detail); skeletons with weights; CC0 clothing and proxies | Assets **CC0**; code AGPL/GPL, which we would not use | **Best candidate** |
| SMPL / SMPL-X / FLAME | Statistical body and face models | Non-commercial research licences | Excluded unless licensed |
| MetaHuman | Highest quality | EULA ties use to Unreal Engine | Excluded: conflicts with the no-Unreal-dependency requirement |
| Daz / Character Creator | High quality | Proprietary; game redistribution needs paid licences | Excluded without purchase authorization |

**What B keeps:** Character DNA schema, provenance and locks; the studio UI, renderer, physics, clips and GLB/validators;
the hair head-frame system; the LOD and kit modules. **What B changes:** mesh, morph source, rig mapping, garment
fitting, expressions.

| Aspect | B with MakeHuman CC0 |
|---|---|
| Visual potential | High for the face: real lids, lip edges, nostrils and creases; proper UVs allow skin textures later |
| Morph compatibility | Its macro targets map onto most of our 53 sliders (gender/femininity, muscle, weight/fat, height, proportions, face). Some sliders need new targets authored as deltas. DNA stays parameter-based; a v2-to-v3 adapter maps traits, and v1/v2 geometry stays reproducible from their commits |
| Rigging | Ships skeletons with weights. Map them to our 64-joint humanoid skeleton (names, rest pose to A-pose) or adopt theirs with a mapping table for clips and physics |
| Garments | `clothing.py` fits garments from the body SDF field. B needs a mesh-to-distance field (compute once per build) or CC0 proxy clothes. **This is the largest integration risk** |
| Expressions and blink | Face targets or face bones provide closable lids; blink becomes a correct morph |
| Studio bake cost | **Much lower.** Targets are linear deltas already, so the pack is assembled from data in seconds or minutes instead of 105 SDF builds (about 31 min) |
| Implementation effort | Medium-high: importer, target mapping, rig mapping, garment fitting, DNA v3 adapter, tests. Roughly several focused sessions |
| External dependency | **Requires a download** (base mesh plus selected targets, about tens of MB). Needs your explicit permission; the container's package and CDN access was blocked earlier, so the source host must also be reachable |

## 3. Recommendation

**B, with MakeHuman CC0 assets, as generator v3**, gated by a cheap visual proof first:

1. With your permission, download only the base mesh, eyes and a few macro and face targets. Record licence files and hashes.
2. Render that head in the **existing studio renderer** with the current shaders, matched against the v2 head
   (same cameras and lighting), and test a blink target. No integration, no bake. Cost: minutes.
3. **Decision gate:** proceed to full integration only if the side-by-side shows a clearly more believable human.

A is not recommended as the main path. Its ceiling comes from the shape model and topology, and each experiment
costs a full rebuild and bake. The current system stays as generator v2 for compatibility and as a fallback.

## 4. Compute estimate (this container, 4 CPU cores)

| Step | A (per iteration) | B |
|---|---|---|
| Template / mesh | about 1 min rebuild | Import: seconds |
| Studio pack | about 31 min (105 SDF builds) | Seconds to minutes (target arithmetic) |
| Exact export | about 55 s | Expected similar or lower (no SDF projection) |
| Visual proof | Full rebuild + bake | One studio capture (about 3 min) |
