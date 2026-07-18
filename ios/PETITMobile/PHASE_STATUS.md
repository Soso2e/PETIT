# iPhone Assistant Phase Status

## Phase 0 — Tailscale Serve

- Implementation: complete on `feat/phase0-tailscale-serve`
- Real Windows/iPhone validation: in progress
- Required evidence:
  - PETIT opens from iPhone Safari
  - text chat round-trip succeeds
  - mobile-data access succeeds
  - disconnecting Tailscale blocks access

## Phase 1 — SwiftUI Text MVP

- Implementation scaffold: complete
- XcodeGen generation: unverified
- Xcode build and unit tests: unverified
- iPhone real-device E2E: unverified

Implemented:

- HTTPS Tailscale Serve URL storage
- `/api/health` connection check
- `/api/chat` text chat
- stable `session_id`
- bounded in-app history forwarding
- tool-use display
- pending action approve/cancel
- connection and API error display

Next:

1. Generate the Xcode project on macOS.
2. Fix compile or signing issues found by Xcode.
3. Connect to the verified Phase 0 URL.
4. Verify chat and one pending action on a real iPhone.
5. Begin Phase 2 push-to-talk speech input and speech synthesis.
