# Setpoint Write

## Scope

Write temperature setpoints to VR921 Setpoint server features via SPINE call.

## Requirements

### R1: Setpoint server discovery
Identify features with `featureType=18` (Setpoint server) from VR921 detailed discovery. Known locations: DHW circuit e[4]f18, HVAC room e[5,1,1]f18.

### R2: SPINE call with setpointData
Send `cmdClassifier: "call"` datagram containing `setpointData` with a `temperature` value. Payload format:

```json
{
  "setpointData": {
    "setpoints": [
      {"setpointId": 0, "value": 45.0, "valueType": "temperature"}
    ]
  }
}
```

### R3: Write confirmation
VR921 responds with `resultData` containing `errorNumber=0` on success, non-zero on error.

### R4: DHW target temperature
Write to DHW Setpoint server e[4]f18. Accepted range: 35°C–65°C (actual range confirmed by VR921 error handling).

### R5: Room temperature setpoint
Write to HVAC room Setpoint server e[5,1,1]f18. Accepted range depends on HVAC mode.

### R6: No read-back
VR921 does not return current setpoint values. The last successfully written value is cached client-side.
