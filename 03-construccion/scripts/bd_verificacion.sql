-- =====================================================================
-- PLASEA - Verificacion solo consultas de lectura
-- Ejecutar despues de plasea_esquema.sql y bd_datos_iniciales.sql.
-- =====================================================================
USE plasea;

-- 1) La base existe con la codificacion esperada (utf8mb4 / utf8mb4_spanish_ci)
SELECT schema_name, default_character_set_name, default_collation_name
FROM information_schema.schemata WHERE schema_name = 'plasea';

-- 2) Tablas y su proposito
SELECT table_name, engine, table_rows, table_comment
FROM information_schema.tables WHERE table_schema = 'plasea' ORDER BY table_name;

-- 3) Columnas
SELECT table_name, ordinal_position, column_name, column_type, is_nullable, column_default, column_key
FROM information_schema.columns WHERE table_schema = 'plasea'
ORDER BY table_name, ordinal_position;

-- 4) Claves primarias y unicas
SELECT tc.table_name, tc.constraint_type, tc.constraint_name,
       GROUP_CONCAT(kcu.column_name ORDER BY kcu.ordinal_position) AS columnas
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON kcu.constraint_schema = tc.constraint_schema
 AND kcu.table_name = tc.table_name AND kcu.constraint_name = tc.constraint_name
WHERE tc.table_schema = 'plasea' AND tc.constraint_type IN ('PRIMARY KEY','UNIQUE')
GROUP BY tc.table_name, tc.constraint_type, tc.constraint_name
ORDER BY tc.table_name, tc.constraint_type DESC, tc.constraint_name;

-- 5) Claves foraneas (relaciones) con sus acciones
SELECT kcu.table_name AS tabla_hija, kcu.constraint_name,
       GROUP_CONCAT(kcu.column_name ORDER BY kcu.ordinal_position) AS columnas_hija,
       kcu.referenced_table_name AS tabla_padre,
       GROUP_CONCAT(kcu.referenced_column_name ORDER BY kcu.ordinal_position) AS columnas_padre,
       rc.delete_rule, rc.update_rule
FROM information_schema.key_column_usage kcu
JOIN information_schema.referential_constraints rc
  ON rc.constraint_schema = kcu.constraint_schema AND rc.constraint_name = kcu.constraint_name
WHERE kcu.table_schema = 'plasea' AND kcu.referenced_table_name IS NOT NULL
GROUP BY kcu.table_name, kcu.constraint_name, kcu.referenced_table_name, rc.delete_rule, rc.update_rule
ORDER BY kcu.table_name, kcu.constraint_name;

-- 6) Alguna FK sin accion RESTRICT (debe devolver 0 filas)
SELECT constraint_name, delete_rule, update_rule
FROM information_schema.referential_constraints
WHERE constraint_schema = 'plasea' AND (delete_rule <> 'RESTRICT' OR update_rule <> 'RESTRICT');

-- 7) Indices
SELECT table_name, index_name, IF(non_unique = 0, 'UNICO', 'NO UNICO') AS tipo,
       GROUP_CONCAT(column_name ORDER BY seq_in_index) AS columnas
FROM information_schema.statistics WHERE table_schema = 'plasea'
GROUP BY table_name, index_name, non_unique
ORDER BY table_name, index_name;

-- 8) Restricciones CHECK
SELECT table_name, constraint_name, check_clause
FROM information_schema.check_constraints WHERE constraint_schema = 'plasea'
ORDER BY table_name, constraint_name;

-- 9) Triggers
SELECT trigger_name, event_manipulation, event_object_table, action_timing
FROM information_schema.triggers WHERE trigger_schema = 'plasea' ORDER BY event_object_table, trigger_name;

-- 10) Datos iniciales
SELECT 'roles' AS catalogo, COUNT(*) AS filas, 3 AS esperado FROM roles
UNION ALL SELECT 'programas_academicos', COUNT(*), 1 FROM programas_academicos
UNION ALL SELECT 'estados_estudiante', COUNT(*), 5 FROM estados_estudiante
UNION ALL SELECT 'causas_no_continuidad', COUNT(*), 5 FROM causas_no_continuidad
UNION ALL SELECT 'tipos_evento_bitacora', COUNT(*), 11 FROM tipos_evento_bitacora
UNION ALL SELECT 'configuraciones_alerta', COUNT(*), 1 FROM configuraciones_alerta;
