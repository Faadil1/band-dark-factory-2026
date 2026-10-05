# Pocketful Stage 3 factory bootstrap

This commit installs only the Stage 3 execution machinery and the pinned official Stage 3 specification from `band-ai/dark-factory-wearedevs@803560d2a678ace1414465c098eb0ab5380ffade`.

It does **not** pre-seed `pocketful-result/stage-3/`.

The actual Stage 3 implementation must originate in a fresh BAND room after this workflow exists on the default branch.
Accepted Stage 2 remains frozen at `3b46422054dee1aa65379bd5efbca33988084fd2`, promoted through `068fe2c70c83b55ad6ec7469d1d60b6dfb1eea99`.

Stage 3 inherits the complete Stage 1 and Stage 2 requirements. The independent Reviewer is explicitly bound to the pinned official isolated harness with `--stage 3`; hidden tests and exhaustive normative conformance remain UNKNOWN until separately evidenced.
