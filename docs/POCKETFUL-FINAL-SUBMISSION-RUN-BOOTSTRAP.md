# Pocketful final submission-run bootstrap

This bootstrap installs execution machinery only. It does not contain or pre-seed a final product result.

The final workflow is triggered only by a fresh branch named `submission/pocketful-final-run-N`. On the runner it:

1. removes prior product-result implementations from the execution workspace;
2. creates one fresh BAND room;
3. initializes one fresh git result repository;
4. builds Stage 1 through Stage 4 sequentially, copying only the accepted prior stage forward;
5. independently reviews every exact stage commit with the pinned official isolated harness;
6. runs cumulative independent assurance after Stage 4;
7. packages the fresh git repository as a bundle while leaving `room.json` absent.

The full `room.json` remains a protected human BAND-console download after the room is complete. No workflow may fabricate it.
