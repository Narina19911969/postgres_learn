REVOKE SELECT ON inventory.worker_order_items_view FROM worker;
REVOKE SELECT ON inventory.worker_orders_view FROM worker;

DROP VIEW IF EXISTS inventory.worker_order_items_view;
DROP VIEW IF EXISTS inventory.worker_orders_view;

