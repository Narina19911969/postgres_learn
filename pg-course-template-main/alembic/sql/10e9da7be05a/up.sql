GRANT USAGE, CREATE ON SCHEMA catalog TO catalog_manager;
GRANT USAGE ON SCHEMA catalog TO sales_manager;
GRANT USAGE ON SCHEMA catalog TO PUBLIC;

-- Текущие таблицы и последовательности (SERIAL)
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA catalog TO catalog_manager;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA catalog TO catalog_manager;

GRANT SELECT ON ALL TABLES IN SCHEMA catalog TO PUBLIC;

-- АВТО-ПРАВА НА БУДУЩЕЕ в схеме catalog:
-- Все новые таблицы/последовательности будут полностью доступны catalog_manager
ALTER DEFAULT PRIVILEGES IN SCHEMA catalog GRANT ALL PRIVILEGES ON TABLES TO catalog_manager;
ALTER DEFAULT PRIVILEGES IN SCHEMA catalog GRANT ALL PRIVILEGES ON SEQUENCES TO catalog_manager;

-- Все новые таблицы будут автоматически доступны на чтение для sales_manager и PUBLIC
ALTER DEFAULT PRIVILEGES IN SCHEMA catalog GRANT SELECT ON TABLES TO PUBLIC;


-- =====================================================================
-- 2. СХЕМА SALES (Управление только для sales_manager)
-- =====================================================================
-- Права на саму схему
GRANT USAGE, CREATE ON SCHEMA sales TO sales_manager;

-- Текущие таблицы и последовательности (SERIAL)
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA sales TO sales_manager;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA sales TO sales_manager;

-- АВТО-ПРАВА НА БУДУЩЕЕ в схеме sales:
-- Все новые объекты будут автоматически полностью доступны sales_manager
ALTER DEFAULT PRIVILEGES IN SCHEMA sales GRANT ALL PRIVILEGES ON TABLES TO sales_manager;
ALTER DEFAULT PRIVILEGES IN SCHEMA sales GRANT ALL PRIVILEGES ON SEQUENCES TO sales_manager;
