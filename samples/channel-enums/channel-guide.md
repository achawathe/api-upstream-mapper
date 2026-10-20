# Customer Channel API value translations

These synthetic examples demonstrate the mapper; they are not a real provider's contract.
Attach this guide to channel.yaml. Each translation is specific to its endpoint and field.

## GET /orders
status: Allowed values: PROCESSING, COMPLETED, FAILED, UNKNOWN.
status: "in progress" -> "PROCESSING"; "packing" -> "PROCESSING"; "done" -> "COMPLETED"; "rejected" -> "FAILED".

## GET /shipments
deliveryState: Allowed values: IN_TRANSIT, DELIVERED, UNKNOWN.
deliveryState: "out for delivery" -> "IN_TRANSIT"; "received by customer" -> "DELIVERED".

Unknown strings must be reviewed. Selecting UNKNOWN as a fallback is an explicit
channel decision; neither spelling similarity nor a local model may invent a status.
