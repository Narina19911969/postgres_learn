
-- =====================================================================
-- НАСТРОЙКА ДОСТУПА (ПРАВА НА ЧТЕНИЕ ДЛЯ ВСЕХ РОЛЕЙ И НА БУДУЩЕЕ)
-- =====================================================================
-- Разрешаем использовать схему текущим менеджерам и всем ролям в будущем (PUBLIC)
GRANT USAGE ON SCHEMA auth TO catalog_manager;
GRANT USAGE ON SCHEMA auth TO sales_manager;
GRANT USAGE ON SCHEMA auth TO PUBLIC;

-- Выдаем права на чтение текущей таблицы пользователей
GRANT SELECT ON ALL TABLES IN SCHEMA auth TO catalog_manager;
GRANT SELECT ON ALL TABLES IN SCHEMA auth TO sales_manager;
GRANT SELECT ON ALL TABLES IN SCHEMA auth TO PUBLIC;

-- Настраиваем авто-выдачу SELECT на любые таблицы в схеме auth, которые появятся в будущем
ALTER DEFAULT PRIVILEGES IN SCHEMA auth GRANT SELECT ON TABLES TO catalog_manager;
ALTER DEFAULT PRIVILEGES IN SCHEMA auth GRANT SELECT ON TABLES TO sales_manager;
ALTER DEFAULT PRIVILEGES IN SCHEMA auth GRANT SELECT ON TABLES TO PUBLIC;
