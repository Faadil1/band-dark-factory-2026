# BAND Coordinator Connectivity Trigger

Purpose: trigger the no-LLM/no-cost remote Coordinator connectivity probe.

Expected proof:
- repository secrets are present;
- GET /api/v1/agent/me authenticates the Coordinator;
- WebSocket connects to BAND;
- agent_rooms:<Coordinator ID> joins successfully;
- Phoenix heartbeat is acknowledged.

No product code or Pocketful run is started by this trigger.
