ALTER TABLE sales.orders 
ADD COLUMN created_by INTEGER NOT NULL DEFAULT 1;

ALTER TABLE sales.orders
ADD CONSTRAINT fk_orders_created_by
FOREIGN KEY (created_by)
REFERENCES auth.users(id)
ON DELETE RESTRICT;

ALTER TABLE sales.orders 
ALTER COLUMN created_by DROP DEFAULT;
