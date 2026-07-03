# HVAC Modes

## Scope

Read and write HVAC operating modes on VR921 HVAC server features.

## Requirements

### R1: HVAC server discovery
Identify features with `featureType=9` (HVAC server) from VR921 detailed discovery. Known locations: DHW circuit e[4]f9, HVAC room e[5,1,1]f9.

### R2: SPINE call with hvacModeListData
Send `cmdClassifier: "call"` datagram with `hvacModeListData` containing desired operating mode.

```json
{
  "hvacModeListData": {
    "hvacMode": [
      {"mode": "heating", "operatingMode": "normal"}
    ]
  }
}
```

### R3: Supported modes
Modes supported by VR921: `heating`, `cooling`, `ventilation`, `standby`, `auto`. Exact values confirmed from VR921 error handling.

### R4: Mode confirmation
VR921 responds with `resultData` containing `errorNumber=0` on success.

### R5: Notifications
VR921 does not send mode change notifications despite subscription. No live mode read-back available.

### R6: Cooling activation
VR921 accepts cooling mode. Heat pump must support cooling (Vaillant heat pumps with reversible cycle).
