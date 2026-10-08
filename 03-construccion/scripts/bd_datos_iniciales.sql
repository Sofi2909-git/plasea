-- =====================================================================
-- PLASEA - Datos iniciales indispensables
-- Ruta: 03-construccion/scripts/bd_datos_iniciales.sql
-- Requiere haber ejecutado antes 02-arquitectura/modelo-datos/plasea_esquema.sql
-- No crea usuarios: el primer Administrador del sistema se crea con el
-- procedimiento de la guia (el hash lo genera la aplicacion).
-- =====================================================================
SET NAMES utf8mb4;
USE plasea;

-- Roles fijos (RF-02)
INSERT INTO roles (codigo, nombre) VALUES
  ('profesor',              'Profesor'),
  ('auditor_academico',     'Auditor académico'),
  ('administrador_sistema', 'Administrador del sistema')
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre);

-- Programa academico unico del alcance
INSERT INTO programas_academicos (nombre) VALUES ('Ingeniería de Sistemas')
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre);

-- Estados del estudiante (RF-22)
INSERT INTO estados_estudiante (codigo, nombre) VALUES
  ('activo',          'Activo'),
  ('graduado',        'Graduado'),
  ('retirado_formal', 'Retirado formal'),
  ('aplazo_semestre', 'Aplazó semestre'),
  ('cancelado',       'Cancelado')
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre);

-- Causas de no continuidad (RF-52)
INSERT INTO causas_no_continuidad (codigo, nombre) VALUES
  ('economica', 'Económica'),
  ('academica', 'Académica'),
  ('personal',  'Personal'),
  ('laboral',   'Laboral'),
  ('otra',      'Otra')
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre);

-- Eventos de la bitacora (RF-61)
INSERT INTO tipos_evento_bitacora (codigo, descripcion) VALUES
  ('inicio_sesion',         'Inicio de sesión'),
  ('cierre_sesion',         'Cierre de sesión (voluntario o por inactividad)'),
  ('intento_fallido',       'Intento fallido de inicio de sesión'),
  ('cambio_administrativo', 'Cambio administrativo sobre cuentas, estructura académica, estudiantes o inscripciones'),
  ('envio_registro',        'Envío del registro de un curso en un corte'),
  ('correccion',            'Corrección de notas o asistencia'),
  ('cierre_corte',          'Cierre de un corte (manual o automático)'),
  ('reapertura',            'Reapertura excepcional de un curso'),
  ('cierre_reapertura',     'Cierre manual de una reapertura excepcional'),
  ('importacion',           'Importación de estudiantes e inscripciones desde CSV'),
  ('exportacion',           'Exportación de datos a CSV')
ON DUPLICATE KEY UPDATE descripcion = VALUES(descripcion);

-- Umbrales de alerta por defecto (RF-20): solo si aun no existe ninguna configuracion
INSERT INTO configuraciones_alerta
  (nota_aprobacion, limite_perdida_inasistencia, umbral_amarillo_inasistencia,
   nota_amarilla_minima, nota_amarilla_maxima, creado_por_usuario_id)
SELECT 3.0, 30.00, 20.00, 3.0, 3.4, NULL
WHERE NOT EXISTS (SELECT 1 FROM configuraciones_alerta);
