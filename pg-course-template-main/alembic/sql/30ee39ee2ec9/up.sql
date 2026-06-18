CREATE SCHEMA IF NOT EXISTS sales;


CREATE TABLE sales.orders (
    id SERIAL PRIMARY KEY,
    status VARCHAR(20) NOT NULL DEFAULT 'unpublished',
    total_amount NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    warehouse_id INT NOT NULL REFERENCES catalog.warehouses(id) ON DELETE RESTRICT
);

CREATE TABLE sales.order_items (
    order_id INT NOT NULL REFERENCES sales.orders(id) ON DELETE CASCADE,
    product_id INT NOT NULL REFERENCES catalog.products(id) ON DELETE RESTRICT,
    quantity INT NOT NULL CHECK (quantity > 0),
    

    PRIMARY KEY (order_id, product_id)
);
