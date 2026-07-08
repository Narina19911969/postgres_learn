CREATE OR REPLACE VIEW inventory.worker_orders_view AS
SELECT id AS order_id, warehouse_id, status FROM sales.orders;

CREATE OR REPLACE VIEW inventory.worker_order_items_view AS
SELECT order_id, product_id, quantity FROM sales.order_items;

GRANT SELECT ON inventory.worker_orders_view TO worker;
GRANT SELECT ON inventory.worker_order_items_view TO worker;

