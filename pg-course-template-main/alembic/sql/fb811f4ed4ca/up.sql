CREATE OR REPLACE VIEW inventory.worker_orders_view AS
SELECT id AS order_id, warehouse_id FROM sales.orders;

GRANT SELECT ON inventory.worker_orders_view TO worker;
GRANT SELECT ON inventory.worker_order_items_view TO worker;

