# Pocketful Stage 4 factory bootstrap

This commit installs only the Stage 4 execution machinery and the pinned official Stage 4 specification from `band-ai/dark-factory-wearedevs@803560d2a678ace1414465c098eb0ab5380ffade`.

It does **not** pre-seed `pocketful-result/stage-4/`.

The actual Stage 4 implementation must originate in a fresh BAND room after this workflow exists on the default branch.
Accepted Stage 3 remains frozen at `e88148c01348a22d8cf6d2c1d4940e6907472df1`, promoted through `0bcda50d3e1138ca287a51faef778f22aee53d0f`.

Stage 4 inherits the complete Stage 1, Stage 2 and Stage 3 requirements. The independent Reviewer is explicitly bound to the pinned official isolated harness with `--stage 4`; hidden tests and exhaustive normative conformance remain UNKNOWN until separately evidenced.
