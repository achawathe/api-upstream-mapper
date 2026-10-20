# Customer Channel API reference

Synthetic API documentation for the mapper example. Attach to channel.yaml.

## GET /orders
status describes the order's fulfillment state.
status: Allowed values: PROCESSING, COMPLETED, FAILED, UNKNOWN.
status: PROCESSING means the order is being prepared.
status: COMPLETED means the order has been fulfilled.
status: FAILED means the order could not be fulfilled.
status: UNKNOWN means the fulfillment state is unavailable.

## GET /shipments
deliveryState describes the shipment's delivery state.
deliveryState: Allowed values: IN_TRANSIT, DELIVERED, UNKNOWN.
deliveryState: IN_TRANSIT means the shipment is travelling to the customer.
deliveryState: DELIVERED means the customer has received the shipment.
deliveryState: UNKNOWN means the delivery state is unavailable.
