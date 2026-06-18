CREATE SCHEMA IF NOT EXISTS catalog;

-- 2. Таблица категорий
CREATE TABLE catalog.product_categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE
);

-- 3. Таблица товаров (содержит внешний ключ на категории)
CREATE TABLE catalog.products (
    id SERIAL PRIMARY KEY,
    sku VARCHAR(30) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    price NUMERIC(12, 2) NOT NULL CHECK (price >= 0),
    category_id INTEGER NOT NULL REFERENCES catalog.product_categories(id) ON DELETE RESTRICT
);

-- 4. Таблица складов
CREATE TABLE catalog.warehouses (
    id SERIAL PRIMARY KEY,
    city VARCHAR(100) NOT NULL,
    address VARCHAR(255) NOT NULL,
    label VARCHAR(255),
    is_central BOOLEAN NOT NULL DEFAULT FALSE
);



