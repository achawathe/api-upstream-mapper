# Fulfillment Provider API reference

Synthetic API documentation for the mapper example. Attach to provider.yaml.

## GET /orders
status describes the order's fulfillment state.
status: Possible values: "in progress", "packing", "done", "rejected".
status: "in progress" means the order is being prepared.
status: "packing" means the order is being prepared.
status: "done" means the order has been fulfilled.
status: "rejected" means the order could not be fulfilled.

## GET /shipments
deliveryState describes the shipment's delivery state.
deliveryState: Possible values: "out for delivery", "received by customer".
deliveryState: "out for delivery" means the shipment is travelling to the customer.
deliveryState: "received by customer" means the customer has received the shipment.
