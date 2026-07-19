# SHIP/SPINE Protocol

## Scope

Transport layer for EEBUS communication between client and VR921.

## Requirements

### R1: SHIP handshake
Implement 5-phase SHIP handshake: CMI Init → HELLO → Protocol → PIN → Access Methods.

### R2: Certificate
Generate self-signed X.509 client certificate. Extract SKI for identity. Reuse on reconnect.

### R3: Pairing
First connection requires trust confirmation in myVaillant app. Client sends HELLO phase=ready, VR921 responds phase=pending until user approves.

### R4: SPINE datagrams
Read, call, result, notify datagram types. EEBUS array-wrapped JSON encoding.

### R5: Keep-alive
Send HELLO phase=ready every 60s if idle. Handle timeout/reconnect.

### R6: Reconnect
Exponential backoff on disconnect (1s, 2s, 4s, ... max 5min).
