ALTER DEFAULT PRIVILEGES IN SCHEMA inventory REVOKE ALL PRIVILEGES ON TABLES FROM inventory_manager;
DROP TABLE IF EXISTS inventory.transfer_items;
DROP TABLE IF EXISTS inventory.transfers;
DROP TABLE IF EXISTS inventory.delivery_items;
DROP TABLE IF EXISTS inventory.deliveries;
DROP TABLE IF EXISTS inventory.stock;
DROP TABLE IF EXISTS catalog.routes;
