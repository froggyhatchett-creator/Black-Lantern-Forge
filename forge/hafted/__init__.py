"""Hafted families (Step 5B): one_hand_axe, two_hand_axe, mace, war_hammer.

A shared hafted framework, plus one generator module per family:
  shapes        geometry primitives
  model         parameter blocks, checks, HaftedAsset, Joint
  haft          the shared haft, grip wrap and butt cap
  axe           the shared axe builder for both axe families
  presentation  forge.hafted-presentation v1
The frozen short sword and the Step 5A blade families are unchanged. This package reuses two
Step 5A functions as they are: the general sweep (forge.blades.shapes) and the
normal and UV algorithms (forge.blades.presentation). It changes neither.
"""
