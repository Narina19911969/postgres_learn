
CREATE TABLE catalog.cities (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);


CREATE SCHEMA IF NOT EXISTS inventory;

CREATE TABLE catalog.routes (
    from_city_id INT NOT NULL REFERENCES catalog.cities(id) ON DELETE RESTRICT,
    to_city_id INT NOT NULL REFERENCES catalog.cities(id) ON DELETE RESTRICT,
    duration INTERVAL NOT NULL,
    total_threshold DECIMAL NOT NULL CHECK (total_threshold >= 0),
    PRIMARY KEY (from_city_id, to_city_id)
);


CREATE TABLE inventory.stock (
    warehouse_id INT NOT NULL REFERENCES catalog.warehouses(id) ON DELETE RESTRICT,
    product_id INT NOT NULL REFERENCES catalog.products(id) ON DELETE RESTRICT,
    quantity INT NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    reserved INT NOT NULL DEFAULT 0 CHECK (reserved >= 0),
    PRIMARY KEY (warehouse_id, product_id)
);


CREATE TABLE inventory.deliveries (
    id SERIAL PRIMARY KEY,
    order_id INT NOT NULL REFERENCES sales.orders(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'shipping', 'shipped')),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    shipped_at TIMESTAMP
);


CREATE TABLE inventory.delivery_items (
    delivery_id INT NOT NULL REFERENCES inventory.deliveries(id) ON DELETE CASCADE,
    product_id INT NOT NULL REFERENCES catalog.products(id) ON DELETE RESTRICT,
    quantity INT NOT NULL CHECK (quantity > 0),
    status VARCHAR(20) NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'shipped')),
    PRIMARY KEY (delivery_id, product_id)
);


CREATE TABLE inventory.transfers (
    id SERIAL PRIMARY KEY,
    src_warehouse_id INT NOT NULL REFERENCES catalog.warehouses(id) ON DELETE RESTRICT,
    dst_warehouse_id INT NOT NULL REFERENCES catalog.warehouses(id) ON DELETE RESTRICT,
    status VARCHAR(20) NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'shipping', 'in_transit', 'arrived', 'received')),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    started_at TIMESTAMP,
    arriving_at TIMESTAMP,
    received_at TIMESTAMP
);


CREATE TABLE inventory.transfer_items (
    transfer_id INT NOT NULL REFERENCES inventory.transfers(id) ON DELETE CASCADE,
    product_id INT NOT NULL REFERENCES catalog.products(id) ON DELETE RESTRICT,
    quantity INT NOT NULL CHECK (quantity > 0),
    status VARCHAR(20) NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'shipped', 'received')),
    PRIMARY KEY (transfer_id, product_id)
);


GRANT ALL PRIVILEGES ON catalog.routes TO inventory_manager;

GRANT USAGE, CREATE ON SCHEMA inventory TO inventory_manager;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA inventory TO inventory_manager;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA inventory TO inventory_manager;
ALTER DEFAULT PRIVILEGES IN SCHEMA inventory GRANT ALL PRIVILEGES ON TABLES TO inventory_manager;

GRANT USAGE ON SCHEMA sales TO inventory_manager;
GRANT SELECT ON ALL TABLES IN SCHEMA sales TO inventory_manager;
GRANT UPDATE (status) ON sales.orders TO inventory_manager;

GRANT USAGE ON SCHEMA catalog TO inventory_manager;
GRANT SELECT ON ALL TABLES IN SCHEMA catalog TO inventory_manager;


GRANT SELECT ON catalog.routes TO worker;

GRANT USAGE ON SCHEMA inventory TO worker;
GRANT SELECT, UPDATE ON inventory.stock TO worker;
GRANT SELECT, UPDATE ON inventory.deliveries TO worker;
GRANT SELECT, UPDATE ON inventory.delivery_items TO worker;
GRANT SELECT, UPDATE ON inventory.transfers TO worker;
GRANT SELECT, UPDATE ON inventory.transfer_items TO worker;

GRANT USAGE ON SCHEMA catalog TO worker;
GRANT SELECT ON catalog.cities, catalog.warehouses, catalog.products, catalog.product_categories TO worker;

GRANT USAGE ON SCHEMA auth TO inventory_manager, worker;
GRANT SELECT ON auth.users TO inventory_manager, worker;
