# mDNS Discovery

## Scope

Discover VR921 gateways on the local network via mDNS.

## Requirements

### R1: Service type
Listen for `_ship._tcp.local.` mDNS service type.

### R2: Candidate tracking
Collect VR921 candidates from mDNS packets. Store IP, port, SKI from TXT record.

### R3: Connection
Connect to candidate via `wss://<ip>:<port>/ship/` with TLS WebSocket.

### R4: Timeout
Fail after 30 seconds if no VR921 discovered.
