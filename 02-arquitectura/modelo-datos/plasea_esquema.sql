-- =====================================================================
-- PLASEA - Esquema de base de datos
-- Ruta: 02-arquitectura/modelo-datos/plasea_esquema.sql
--
-- * No contiene DROP ni datos: puede ejecutarse varias veces sin perder
--   informacion (CREATE ... IF NOT EXISTS). Para reiniciar el entorno de
--   desarrollo use 03-construccion/scripts/bd_reiniciar_desarrollo.sql.
-- * No contiene contrasenas ni secretos.
-- * Los catalogos y la configuracion inicial se cargan con
--   03-construccion/scripts/bd_datos_iniciales.sql.
-- * Convenciones: tablas en plural, snake_case, ASCII, espanol.
--   PK = id (BIGINT UNSIGNED). FK = <entidad_singular>_id (o <rol>_usuario_id).
--   Restricciones con nombre: pk/fk_<tabla>_<ref>, uq_<tabla>_<cols>,
--   ck_<tabla>_<regla>, ix_<tabla>_<cols>, tg_<tabla>_<regla>.
-- * ON DELETE / ON UPDATE: RESTRICT en todas las FK. La informacion
--   academica nunca se elimina (Acta, seccion 4 de las instrucciones).
-- * Fechas y horas: DATETIME en hora de Colombia (UTC-5, sin horario de
--   verano). La conexion de la aplicacion debe fijar time_zone = '-05:00'.
-- =====================================================================

SET NAMES utf8mb4;

CREATE DATABASE IF NOT EXISTS plasea
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_spanish_ci;

USE plasea;

-- =====================================================================
-- E1. ACCESO Y CUENTAS (RF-01 a RF-12)
-- =====================================================================

CREATE TABLE IF NOT EXISTS roles (
  id      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  codigo  VARCHAR(30) NOT NULL COMMENT 'Identificador estable usado por la aplicacion',
  nombre  VARCHAR(50) NOT NULL COMMENT 'Nombre para mostrar',
  PRIMARY KEY (id),
  UNIQUE KEY uq_roles_codigo (codigo),
  UNIQUE KEY uq_roles_nombre (nombre)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_spanish_ci
  COMMENT='Catalogo de los 3 roles fijos (RF-02)';

CREATE TABLE IF NOT EXISTS usuarios (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  nombre_completo    VARCHAR(150) NOT NULL,
  correo             VARCHAR(254) NOT NULL COMMENT 'Correo institucional, unico sin distinguir mayusculas (RF-08)',
  contrasena_hash    VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin NULL
                     COMMENT 'Solo el hash producido por la aplicacion; NULL mientras la cuenta esta pendiente de activacion',
  rol_id             BIGINT UNSIGNED NOT NULL,
  estado_cuenta      VARCHAR(25) NOT NULL DEFAULT 'pendiente_activacion'
                     COMMENT 'pendiente_activacion | activa | inactiva | bloqueada (bloqueo administrativo, RF-11)',
  intentos_fallidos  TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'Intentos consecutivos fallidos (RF-05)',
  bloqueo_hasta      DATETIME NULL COMMENT 'Bloqueo temporal automatico por intentos fallidos (RF-05); NULL si no hay',
  creado_en          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  actualizado_en     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_usuarios_correo (correo),
  KEY ix_usuarios_rol_estado (rol_id, estado_cuenta),
  KEY ix_usuarios_nombre_completo (nombre_completo),
  CONSTRAINT fk_usuarios_roles FOREIGN KEY (rol_id) REFERENCES roles (id)
    ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_usuarios_estado_cuenta CHECK (estado_cuenta IN
    ('pendiente_activacion','activa','inactiva','bloqueada')),
  CONSTRAINT ck_usuarios_hash_si_activa CHECK
    (estado_cuenta NOT IN ('activa','bloqueada') OR contrasena_hash IS NOT NULL)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_spanish_ci
  COMMENT='Cuentas de usuario. Nunca se eliminan, solo se desactivan (RF-11)';

CREATE TABLE IF NOT EXISTS tokens_cuenta (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  usuario_id    BIGINT UNSIGNED NOT NULL,
  proposito     VARCHAR(20) NOT NULL COMMENT 'activacion (RF-08/09) | restablecimiento (RF-06/07)',
  token_hash    CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL
                COMMENT 'SHA-256 en hexadecimal del token enviado por correo; el token nunca se guarda',
  creado_en     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  vence_en      DATETIME NOT NULL COMMENT 'Vigencia parametrizable en el archivo de configuracion',
  usado_en      DATETIME NULL COMMENT 'Uso unico: se llena al consumir el enlace',
  invalidado_en DATETIME NULL COMMENT 'Se llena cuando un enlace nuevo o un cambio de estado lo reemplaza',
  PRIMARY KEY (id),
  UNIQUE KEY uq_tokens_cuenta_token_hash (token_hash),
  KEY ix_tokens_cuenta_usuario_proposito (usuario_id, proposito),
  CONSTRAINT fk_tokens_cuenta_usuarios FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
    ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_tokens_cuenta_proposito CHECK (proposito IN ('activacion','restablecimiento')),
  CONSTRAINT ck_tokens_cuenta_hash CHECK (token_hash REGEXP '^[0-9a-f]{64}$'),
  CONSTRAINT ck_tokens_cuenta_vigencia CHECK (vence_en > creado_en)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_spanish_ci
  COMMENT='Enlaces de un solo uso para activar cuenta y restablecer contrasena';

CREATE TABLE IF NOT EXISTS sesiones_usuario (
  id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  usuario_id           BIGINT UNSIGNED NOT NULL,
  rol_id               BIGINT UNSIGNED NOT NULL COMMENT 'Rol vigente al iniciar sesion: un cambio de rol aplica desde el siguiente inicio (RF-10)',
  token_hash           CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL
                       COMMENT 'SHA-256 del identificador opaco guardado en la cookie de sesion',
  creada_en            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  ultima_actividad_en  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Base de la expiracion por inactividad (RF-04)',
  cerrada_en           DATETIME NULL,
  motivo_cierre        VARCHAR(40) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_sesiones_usuario_token_hash (token_hash),
  KEY ix_sesiones_usuario_usuario_cerrada (usuario_id, cerrada_en),
  KEY ix_sesiones_usuario_rol (rol_id),
  CONSTRAINT fk_sesiones_usuario_usuarios FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
    ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_sesiones_usuario_roles FOREIGN KEY (rol_id) REFERENCES roles (id)
    ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_sesiones_usuario_motivo CHECK (motivo_cierre IS NULL OR motivo_cierre IN
    ('cierre_voluntario','inactividad','cuenta_desactivada','cuenta_bloqueada','restablecimiento_contrasena')),
  CONSTRAINT ck_sesiones_usuario_cierre CHECK ((cerrada_en IS NULL) = (motivo_cierre IS NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_spanish_ci
  COMMENT='Sesiones en el servidor: permiten cerrar, expirar e invalidar sesiones (RF-03, RF-04, RF-07, RF-11)';

-- =====================================================================
-- E2. ESTRUCTURA ACADEMICA (RF-13 a RF-20)
-- =====================================================================

CREATE TABLE IF NOT EXISTS programas_academicos (
  id      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  nombre  VARCHAR(100) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_programas_academicos_nombre (nombre)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_spanish_ci
  COMMENT='Catalogo de programas (hoy solo Ingenieria de Sistemas; RF-13, RF-21, RF-53)';

CREATE TABLE IF NOT EXISTS asignaturas (
  id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  codigo                VARCHAR(20) NOT NULL,
  nombre                VARCHAR(150) NOT NULL,
  programa_academico_id BIGINT UNSIGNED NOT NULL,
  creditos              TINYINT UNSIGNED NOT NULL COMMENT '3 o 4',
  horas_semanales       TINYINT UNSIGNED NOT NULL,
  nivel                 TINYINT UNSIGNED NOT NULL COMMENT 'Nivel de la carrera, 1 a 10',
  creado_en             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  actualizado_en        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_asignaturas_codigo (codigo),
  KEY ix_asignaturas_programa (programa_academico_id),
  CONSTRAINT fk_asignaturas_programas_academicos FOREIGN KEY (programa_academico_id)
    REFERENCES programas_academicos (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_asignaturas_creditos CHECK (creditos IN (3,4)),
  CONSTRAINT ck_asignaturas_horas CHECK (horas_semanales > 0),
  CONSTRAINT ck_asignaturas_nivel CHECK (nivel BETWEEN 1 AND 10)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_spanish_ci
  COMMENT='Asignaturas (sinonimo de materias) - RF-13';

CREATE TABLE IF NOT EXISTS periodos_academicos (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  identificador   VARCHAR(6) NOT NULL COMMENT 'Ejemplo: 2026-2',
  fecha_inicio    DATE NOT NULL,
  fecha_fin       DATE NOT NULL COMMENT 'Fin de las 16 semanas; la duracion exacta la valida la aplicacion',
  en_curso_marca  TINYINT NULL DEFAULT NULL COMMENT '1 = periodo en curso; NULL = no. UNIQUE garantiza uno solo (RF-16)',
  creado_en       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  actualizado_en  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_periodos_academicos_identificador (identificador),
  UNIQUE KEY uq_periodos_academicos_en_curso (en_curso_marca),
  KEY ix_periodos_academicos_fecha_inicio (fecha_inicio),
  CONSTRAINT ck_periodos_academicos_identificador CHECK (identificador REGEXP '^[0-9]{4}-[12]$'),
  CONSTRAINT ck_periodos_academicos_fechas CHECK (fecha_fin > fecha_inicio),
  CONSTRAINT ck_periodos_academicos_marca CHECK (en_curso_marca IS NULL OR en_curso_marca = 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_spanish_ci
  COMMENT='Semestres academicos (RF-16). El orden cronologico lo da fecha_inicio';

CREATE TABLE IF NOT EXISTS cortes (
  id                        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  periodo_academico_id      BIGINT UNSIGNED NOT NULL,
  numero                    TINYINT UNSIGNED NOT NULL COMMENT '1, 2 o 3',
  peso_porcentaje           DECIMAL(5,2) NOT NULL COMMENT 'Por defecto 30, 30 y 40; la suma de 100 la valida la aplicacion (RF-17)',
  fecha_inicio              DATE NOT NULL,
  fecha_fin                 DATE NOT NULL,
  limite_carga              DATE NOT NULL,
  limite_correccion         DATE NOT NULL,
  cerrado_en                DATETIME NULL COMMENT 'NULL = corte abierto',
  tipo_cierre               VARCHAR(10) NULL COMMENT 'manual (RF-36) | automatico (RF-37)',
  cerrado_por_usuario_id    BIGINT UNSIGNED NULL COMMENT 'Auditor que cerro; NULL si fue automatico',
  aviso_resumen_enviado_en  DATETIME NULL COMMENT 'Garantiza un solo correo de resumen por corte cerrado (RF-57)',
  creado_en                 DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  actualizado_en            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_cortes_periodo_numero (periodo_academico_id, numero),
  KEY ix_cortes_cerrado_por (cerrado_por_usuario_id),
  CONSTRAINT fk_cortes_periodos_academicos FOREIGN KEY (periodo_academico_id)
    REFERENCES periodos_academicos (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_cortes_usuarios_cierre FOREIGN KEY (cerrado_por_usuario_id)
    REFERENCES usuarios (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_cortes_numero CHECK (numero BETWEEN 1 AND 3),
  CONSTRAINT ck_cortes_peso CHECK (peso_porcentaje > 0 AND peso_porcentaje <= 100),
  CONSTRAINT ck_cortes_fechas CHECK (fecha_inicio <= fecha_fin),
  CONSTRAINT ck_cortes_limites CHECK (limite_correccion > limite_carga),
  CONSTRAINT ck_cortes_tipo_cierre CHECK (tipo_cierre IS NULL OR tipo_cierre IN ('manual','automatico')),
  CONSTRAINT ck_cortes_cierre_completo CHECK ((cerrado_en IS NULL) = (tipo_cierre IS NULL)),
  CONSTRAINT ck_cortes_cierre_responsable CHECK
    (tipo_cierre IS NULL OR ((tipo_cierre = 'manual') = (cerrado_por_usuario_id IS NOT NULL)))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_spanish_ci
  COMMENT='Los 3 cortes de cada periodo con pesos, plazos y estado de cierre (RF-17, RF-36, RF-37)';

CREATE TABLE IF NOT EXISTS festivos (
  id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  periodo_academico_id  BIGINT UNSIGNED NOT NULL,
  fecha                 DATE NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_festivos_periodo_fecha (periodo_academico_id, fecha),
  CONSTRAINT fk_festivos_periodos_academicos FOREIGN KEY (periodo_academico_id)
    REFERENCES periodos_academicos (id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_spanish_ci
  COMMENT='Festivos del periodo; no hay sesiones esos dias (RF-18, RF-19)';

CREATE TABLE IF NOT EXISTS cursos (
  id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  asignatura_id         BIGINT UNSIGNED NOT NULL,
  periodo_academico_id  BIGINT UNSIGNED NOT NULL,
  codigo                VARCHAR(10) NOT NULL COMMENT 'Ejemplo: T01, T02',
  profesor_usuario_id   BIGINT UNSIGNED NOT NULL COMMENT 'Un solo docente por curso; la aplicacion exige rol Profesor (RF-14)',
  creado_en             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  actualizado_en        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_cursos_asignatura_periodo_codigo (asignatura_id, periodo_academico_id, codigo),
  UNIQUE KEY uq_cursos_id_periodo (id, periodo_academico_id),
  KEY ix_cursos_profesor_periodo (profesor_usuario_id, periodo_academico_id),
  KEY ix_cursos_periodo (periodo_academico_id),
  CONSTRAINT fk_cursos_asignaturas FOREIGN KEY (asignatura_id) REFERENCES asignaturas (id)
    ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_cursos_periodos_academicos FOREIGN KEY (periodo_academico_id)
    REFERENCES periodos_academicos (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_cursos_usuarios_profesor FOREIGN KEY (profesor_usuario_id) REFERENCES usuarios (id)
    ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_spanish_ci
  COMMENT='Cursos de una asignatura en un periodo, con su docente (RF-14)';

CREATE TABLE IF NOT EXISTS bloques_horario (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  curso_id     BIGINT UNSIGNED NOT NULL,
  dia_semana   TINYINT UNSIGNED NOT NULL COMMENT '1 = lunes ... 7 = domingo (ISO 8601)',
  hora_inicio  TIME NOT NULL,
  hora_fin     TIME NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_bloques_horario_curso_dia_inicio (curso_id, dia_semana, hora_inicio),
  CONSTRAINT fk_bloques_horario_cursos FOREIGN KEY (curso_id) REFERENCES cursos (id)
    ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_bloques_horario_dia CHECK (dia_semana BETWEEN 1 AND 7),
  CONSTRAINT ck_bloques_horario_duracion CHECK
    (TIME_TO_SEC(hora_fin) - TIME_TO_SEC(hora_inicio) IN (3600, 7200, 10800))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_spanish_ci
  COMMENT='Horario semanal del curso: sesiones de 1, 2 o 3 horas (RF-15). El traslape lo valida la aplicacion';

CREATE TABLE IF NOT EXISTS sesiones_clase (
  id                                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  curso_id                              BIGINT UNSIGNED NOT NULL,
  fecha                                 DATE NOT NULL,
  hora_inicio                           TIME NOT NULL,
  hora_fin                              TIME NOT NULL,
  duracion_horas                        TINYINT UNSIGNED AS
    (CAST((TIME_TO_SEC(hora_fin) - TIME_TO_SEC(hora_inicio)) / 3600 AS UNSIGNED)) VIRTUAL
    COMMENT 'Calculada: horas que se cargan a cada ausente (RF-28)',
  asistencia_registrada_en              DATETIME NULL COMMENT 'Marca que el profesor registro la asistencia, aunque no haya ausentes (RF-30)',
  asistencia_registrada_por_usuario_id  BIGINT UNSIGNED NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_sesiones_clase_curso_fecha_inicio (curso_id, fecha, hora_inicio),
  KEY ix_sesiones_clase_registrador (asistencia_registrada_por_usuario_id),
  CONSTRAINT fk_sesiones_clase_cursos FOREIGN KEY (curso_id) REFERENCES cursos (id)
    ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_sesiones_clase_usuarios FOREIGN KEY (asistencia_registrada_por_usuario_id)
    REFERENCES usuarios (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_sesiones_clase_duracion CHECK
    (TIME_TO_SEC(hora_fin) - TIME_TO_SEC(hora_inicio) IN (3600, 7200, 10800)),
  CONSTRAINT ck_sesiones_clase_registro CHECK
    ((asistencia_registrada_en IS NULL) = (asistencia_registrada_por_usuario_id IS NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_spanish_ci
  COMMENT='Calendario de sesiones de cada curso, generado desde horario, periodo y festivos (RF-19)';

CREATE TABLE IF NOT EXISTS configuraciones_alerta (
  id                              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  nota_aprobacion                 DECIMAL(2,1) NOT NULL DEFAULT 3.0,
  limite_perdida_inasistencia     DECIMAL(5,2) NOT NULL DEFAULT 30.00 COMMENT 'Porcentaje; se pierde al superarlo',
  umbral_amarillo_inasistencia    DECIMAL(5,2) NOT NULL DEFAULT 20.00 COMMENT 'Porcentaje; tambien aplica al ritmo de inasistencia',
  nota_amarilla_minima            DECIMAL(2,1) NOT NULL DEFAULT 3.0,
  nota_amarilla_maxima            DECIMAL(2,1) NOT NULL DEFAULT 3.4,
  vigente_desde                   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  creado_por_usuario_id           BIGINT UNSIGNED NULL COMMENT 'NULL = configuracion inicial del sistema',
  PRIMARY KEY (id),
  KEY ix_configuraciones_alerta_vigente_desde (vigente_desde),
  KEY ix_configuraciones_alerta_creador (creado_por_usuario_id),
  CONSTRAINT fk_configuraciones_alerta_usuarios FOREIGN KEY (creado_por_usuario_id)
    REFERENCES usuarios (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_configuraciones_alerta_nota CHECK (nota_aprobacion BETWEEN 1.0 AND 5.0),
  CONSTRAINT ck_configuraciones_alerta_porcentajes CHECK
    (umbral_amarillo_inasistencia > 0 AND umbral_amarillo_inasistencia < limite_perdida_inasistencia
     AND limite_perdida_inasistencia <= 100),
  CONSTRAINT ck_configuraciones_alerta_rango_amarillo CHECK
    (nota_amarilla_minima BETWEEN 1.0 AND 5.0 AND nota_amarilla_maxima BETWEEN 1.0 AND 5.0
     AND nota_amarilla_minima <= nota_amarilla_maxima)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_spanish_ci
  COMMENT='Umbrales de alerta versionados: cada cambio es una fila nueva; la vigente es la mas reciente (RF-20)';

-- =====================================================================
-- E3. ESTUDIANTES E INSCRIPCIONES (RF-21 a RF-25)
-- =====================================================================

CREATE TABLE IF NOT EXISTS estados_estudiante (
  id      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  codigo  VARCHAR(30) NOT NULL,
  nombre  VARCHAR(50) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_estados_estudiante_codigo (codigo),
  UNIQUE KEY uq_estados_estudiante_nombre (nombre)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_spanish_ci
  COMMENT='Catalogo: activo, graduado, retirado formal, aplazo semestre, cancelado (RF-22)';

CREATE TABLE IF NOT EXISTS estudiantes (
  id                     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  codigo                 VARCHAR(20) NOT NULL COMMENT 'Codigo estudiantil: identificacion del estudiante en PLASEA',
  nombres                VARCHAR(150) NOT NULL,
  correo                 VARCHAR(254) NOT NULL,
  programa_academico_id  BIGINT UNSIGNED NOT NULL,
  periodo_ingreso        VARCHAR(6) NOT NULL COMMENT 'Cohorte (ejemplo 2022-1). Texto y no FK: puede ser anterior a los periodos registrados',
  creado_en              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  actualizado_en         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_estudiantes_codigo (codigo),
  KEY ix_estudiantes_nombres (nombres),
  KEY ix_estudiantes_periodo_ingreso (periodo_ingreso),
  KEY ix_estudiantes_programa (programa_academico_id),
  CONSTRAINT fk_estudiantes_programas_academicos FOREIGN KEY (programa_academico_id)
    REFERENCES programas_academicos (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_estudiantes_periodo_ingreso CHECK (periodo_ingreso REGEXP '^[0-9]{4}-[12]$')
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_spanish_ci
  COMMENT='Estudiantes. Nunca se eliminan: su situacion se maneja con el historial de estados (RF-21)';

CREATE TABLE IF NOT EXISTS historial_estados_estudiante (
  id                         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  estudiante_id              BIGINT UNSIGNED NOT NULL,
  estado_estudiante_id       BIGINT UNSIGNED NOT NULL,
  fecha_efectiva             DATE NOT NULL,
  registrado_por_usuario_id  BIGINT UNSIGNED NOT NULL,
  creado_en                  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_historial_estados_estudiante_fecha (estudiante_id, fecha_efectiva),
  KEY ix_historial_estados_estudiante_estado (estado_estudiante_id),
  KEY ix_historial_estados_estudiante_registrador (registrado_por_usuario_id),
  CONSTRAINT fk_historial_estados_estudiantes FOREIGN KEY (estudiante_id) REFERENCES estudiantes (id)
    ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_historial_estados_estados FOREIGN KEY (estado_estudiante_id)
    REFERENCES estados_estudiante (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_historial_estados_usuarios FOREIGN KEY (registrado_por_usuario_id)
    REFERENCES usuarios (id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_spanish_ci
  COMMENT='Historial de estados del estudiante; el estado actual es el de fecha_efectiva mas reciente (RF-22)';

CREATE TABLE IF NOT EXISTS matriculas_periodo (
  id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  estudiante_id         BIGINT UNSIGNED NOT NULL,
  periodo_academico_id  BIGINT UNSIGNED NOT NULL,
  semestre_cursado      TINYINT UNSIGNED NOT NULL COMMENT 'Semestre de la carrera que cursa en el periodo, 1 a 10 (RF-23, RF-51)',
  creado_en             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  actualizado_en        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_matriculas_periodo_estudiante_periodo (estudiante_id, periodo_academico_id),
  UNIQUE KEY uq_matriculas_periodo_id_periodo (id, periodo_academico_id),
  KEY ix_matriculas_periodo_periodo_semestre (periodo_academico_id, semestre_cursado),
  CONSTRAINT fk_matriculas_periodo_estudiantes FOREIGN KEY (estudiante_id) REFERENCES estudiantes (id)
    ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_matriculas_periodo_periodos FOREIGN KEY (periodo_academico_id)
    REFERENCES periodos_academicos (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_matriculas_periodo_semestre CHECK (semestre_cursado BETWEEN 1 AND 10)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_spanish_ci
  COMMENT='Participacion de un estudiante en un periodo con su semestre cursado: base de RF-49 a RF-53';

CREATE TABLE IF NOT EXISTS inscripciones (
  id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  matricula_periodo_id  BIGINT UNSIGNED NOT NULL,
  curso_id              BIGINT UNSIGNED NOT NULL,
  periodo_academico_id  BIGINT UNSIGNED NOT NULL COMMENT 'Columna de consistencia: matricula y curso deben ser del mismo periodo',
  retirada_en           DATE NULL COMMENT 'Retiro del curso; la fila se conserva (RF-23)',
  creado_en             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  actualizado_en        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_inscripciones_matricula_curso (matricula_periodo_id, curso_id),
  KEY ix_inscripciones_matricula_periodo (matricula_periodo_id, periodo_academico_id),
  KEY ix_inscripciones_curso_periodo (curso_id, periodo_academico_id),
  CONSTRAINT fk_inscripciones_matriculas_periodo FOREIGN KEY (matricula_periodo_id, periodo_academico_id)
    REFERENCES matriculas_periodo (id, periodo_academico_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_inscripciones_cursos FOREIGN KEY (curso_id, periodo_academico_id)
    REFERENCES cursos (id, periodo_academico_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_spanish_ci
  COMMENT='Inscripcion de un estudiante (via su matricula del periodo) en un curso (RF-23)';

-- =====================================================================
-- E4 y E5. REGISTRO DE ASISTENCIA Y NOTAS, CIERRE DE CORTES (RF-26 a RF-39)
-- =====================================================================

CREATE TABLE IF NOT EXISTS registros_curso_corte (
  id                     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  curso_id               BIGINT UNSIGNED NOT NULL,
  corte_id               BIGINT UNSIGNED NOT NULL,
  estado                 VARCHAR(15) NOT NULL DEFAULT 'pendiente'
                         COMMENT 'pendiente | enviado | cerrado | sin_registro',
  enviado_en             DATETIME NULL,
  enviado_por_usuario_id BIGINT UNSIGNED NULL,
  creado_en              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  actualizado_en         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_registros_curso_corte_curso_corte (curso_id, corte_id),
  KEY ix_registros_curso_corte_corte_estado (corte_id, estado),
  KEY ix_registros_curso_corte_enviador (enviado_por_usuario_id),
  CONSTRAINT fk_registros_curso_corte_cursos FOREIGN KEY (curso_id) REFERENCES cursos (id)
    ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_registros_curso_corte_cortes FOREIGN KEY (corte_id) REFERENCES cortes (id)
    ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_registros_curso_corte_usuarios FOREIGN KEY (enviado_por_usuario_id)
    REFERENCES usuarios (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_registros_curso_corte_estado CHECK
    (estado IN ('pendiente','enviado','cerrado','sin_registro')),
  CONSTRAINT ck_registros_curso_corte_envio CHECK
    ((estado IN ('enviado','cerrado')) = (enviado_en IS NOT NULL)
     AND ((enviado_en IS NULL) = (enviado_por_usuario_id IS NULL)))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_spanish_ci
  COMMENT='Estado del registro de un curso en un corte: borrador a envio a cierre (RF-26, RF-30, RF-35, RF-36)';

CREATE TABLE IF NOT EXISTS reaperturas_curso (
  id                         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  registro_curso_corte_id    BIGINT UNSIGNED NOT NULL,
  motivo                     VARCHAR(500) NOT NULL,
  abierta_por_usuario_id     BIGINT UNSIGNED NOT NULL,
  abierta_en                 DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  cerrada_por_usuario_id     BIGINT UNSIGNED NULL,
  cerrada_en                 DATETIME NULL COMMENT 'NULL = reapertura vigente (RF-39)',
  vigente_marca              TINYINT AS (IF(cerrada_en IS NULL, 1, NULL)) PERSISTENT
                             COMMENT 'Calculada: 1 si vigente. UNIQUE garantiza una sola reapertura vigente por registro',
  PRIMARY KEY (id),
  UNIQUE KEY uq_reaperturas_curso_registro_vigente (registro_curso_corte_id, vigente_marca),
  KEY ix_reaperturas_curso_apertura (abierta_por_usuario_id),
  KEY ix_reaperturas_curso_cierre (cerrada_por_usuario_id),
  CONSTRAINT fk_reaperturas_curso_registros FOREIGN KEY (registro_curso_corte_id)
    REFERENCES registros_curso_corte (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_reaperturas_curso_usuarios_apertura FOREIGN KEY (abierta_por_usuario_id)
    REFERENCES usuarios (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_reaperturas_curso_usuarios_cierre FOREIGN KEY (cerrada_por_usuario_id)
    REFERENCES usuarios (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_reaperturas_curso_motivo CHECK (CHAR_LENGTH(TRIM(motivo)) > 0),
  CONSTRAINT ck_reaperturas_curso_cierre CHECK ((cerrada_en IS NULL) = (cerrada_por_usuario_id IS NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_spanish_ci
  COMMENT='Reaperturas excepcionales por curso y corte, con motivo obligatorio (RF-38, RF-39)';

CREATE TABLE IF NOT EXISTS notas_corte (
  id                          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  inscripcion_id              BIGINT UNSIGNED NOT NULL,
  corte_id                    BIGINT UNSIGNED NOT NULL,
  nota                        DECIMAL(2,1) NOT NULL COMMENT 'Escala 1,0 a 5,0 con un decimal (RF-29)',
  registrada_por_usuario_id   BIGINT UNSIGNED NOT NULL,
  creado_en                   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  actualizado_en              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_notas_corte_inscripcion_corte (inscripcion_id, corte_id),
  KEY ix_notas_corte_corte (corte_id),
  KEY ix_notas_corte_registrador (registrada_por_usuario_id),
  CONSTRAINT fk_notas_corte_inscripciones FOREIGN KEY (inscripcion_id) REFERENCES inscripciones (id)
    ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_notas_corte_cortes FOREIGN KEY (corte_id) REFERENCES cortes (id)
    ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_notas_corte_usuarios FOREIGN KEY (registrada_por_usuario_id) REFERENCES usuarios (id)
    ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_notas_corte_nota CHECK (nota BETWEEN 1.0 AND 5.0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_spanish_ci
  COMMENT='Nota consolidada de un estudiante en un corte; la fila existe solo si hay nota (RF-29)';

CREATE TABLE IF NOT EXISTS ausencias (
  id                          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  sesion_clase_id             BIGINT UNSIGNED NOT NULL,
  inscripcion_id              BIGINT UNSIGNED NOT NULL,
  ausente                     TINYINT(1) NOT NULL DEFAULT 1 COMMENT '1 = ausente; 0 = ausencia corregida (la fila no se elimina)',
  registrada_por_usuario_id   BIGINT UNSIGNED NOT NULL,
  creado_en                   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  actualizado_en              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_ausencias_sesion_inscripcion (sesion_clase_id, inscripcion_id),
  KEY ix_ausencias_inscripcion_ausente (inscripcion_id, ausente),
  KEY ix_ausencias_registrador (registrada_por_usuario_id),
  CONSTRAINT fk_ausencias_sesiones_clase FOREIGN KEY (sesion_clase_id) REFERENCES sesiones_clase (id)
    ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_ausencias_inscripciones FOREIGN KEY (inscripcion_id) REFERENCES inscripciones (id)
    ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_ausencias_usuarios FOREIGN KEY (registrada_por_usuario_id) REFERENCES usuarios (id)
    ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_ausencias_ausente CHECK (ausente IN (0,1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_spanish_ci
  COMMENT='Solo se guardan los ausentes; quien no tiene fila estuvo presente (RF-28)';

CREATE TABLE IF NOT EXISTS historial_notas (
  id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  nota_corte_id         BIGINT UNSIGNED NOT NULL,
  nota_anterior         DECIMAL(2,1) NOT NULL,
  nota_nueva            DECIMAL(2,1) NOT NULL,
  motivo                VARCHAR(500) NOT NULL,
  usuario_id            BIGINT UNSIGNED NOT NULL,
  reapertura_curso_id   BIGINT UNSIGNED NULL COMMENT 'Si la correccion se hizo en una reapertura excepcional (RF-38)',
  creado_en             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_historial_notas_nota_corte (nota_corte_id),
  KEY ix_historial_notas_creado_en (creado_en),
  KEY ix_historial_notas_usuario (usuario_id),
  KEY ix_historial_notas_reapertura (reapertura_curso_id),
  CONSTRAINT fk_historial_notas_notas_corte FOREIGN KEY (nota_corte_id) REFERENCES notas_corte (id)
    ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_historial_notas_usuarios FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
    ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_historial_notas_reaperturas FOREIGN KEY (reapertura_curso_id)
    REFERENCES reaperturas_curso (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_historial_notas_cambio CHECK (nota_anterior <> nota_nueva),
  CONSTRAINT ck_historial_notas_motivo CHECK (CHAR_LENGTH(TRIM(motivo)) > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_spanish_ci
  COMMENT='Correcciones de notas: valor anterior, nuevo, motivo, usuario y fecha (RF-31, RF-33). Inmutable';

CREATE TABLE IF NOT EXISTS historial_ausencias (
  id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  ausencia_id           BIGINT UNSIGNED NOT NULL,
  ausente_anterior      TINYINT(1) NOT NULL,
  ausente_nuevo         TINYINT(1) NOT NULL,
  motivo                VARCHAR(500) NOT NULL,
  usuario_id            BIGINT UNSIGNED NOT NULL,
  reapertura_curso_id   BIGINT UNSIGNED NULL,
  creado_en             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_historial_ausencias_ausencia (ausencia_id),
  KEY ix_historial_ausencias_creado_en (creado_en),
  KEY ix_historial_ausencias_usuario (usuario_id),
  KEY ix_historial_ausencias_reapertura (reapertura_curso_id),
  CONSTRAINT fk_historial_ausencias_ausencias FOREIGN KEY (ausencia_id) REFERENCES ausencias (id)
    ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_historial_ausencias_usuarios FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
    ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_historial_ausencias_reaperturas FOREIGN KEY (reapertura_curso_id)
    REFERENCES reaperturas_curso (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_historial_ausencias_valores CHECK
    (ausente_anterior IN (0,1) AND ausente_nuevo IN (0,1) AND ausente_anterior <> ausente_nuevo),
  CONSTRAINT ck_historial_ausencias_motivo CHECK (CHAR_LENGTH(TRIM(motivo)) > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_spanish_ci
  COMMENT='Correcciones de asistencia (RF-31, RF-33). Inmutable';

-- =====================================================================
-- E6. ALERTAS Y ANALITICA (RF-40 a RF-48)
-- =====================================================================

CREATE TABLE IF NOT EXISTS alertas (
  id                          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  inscripcion_id              BIGINT UNSIGNED NOT NULL,
  corte_id                    BIGINT UNSIGNED NOT NULL,
  configuracion_alerta_id     BIGINT UNSIGNED NOT NULL COMMENT 'Version de umbrales con la que se calculo (RF-20)',
  estado_alerta               VARCHAR(10) NOT NULL COMMENT 'verde | amarilla | roja (RF-43)',
  motivo_nota                 TINYINT(1) NOT NULL DEFAULT 0,
  motivo_inasistencia         TINYINT(1) NOT NULL DEFAULT 0,
  nota_corte                  DECIMAL(2,1) NULL COMMENT 'NULL si el estudiante no tiene nota en el corte',
  nota_acumulada              DECIMAL(4,2) NULL COMMENT 'RF-40: puede tener hasta dos decimales',
  nota_requerida              DECIMAL(5,2) NULL COMMENT 'RF-41: puede superar 5,0 (asignatura perdida por nota); NULL tras el ultimo corte',
  horas_ausentes              SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  horas_dictadas              SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  horas_totales               SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  porcentaje_inasistencia     DECIMAL(5,2) NOT NULL DEFAULT 0 COMMENT 'Horas ausentes / horas totales (RF-42)',
  porcentaje_ritmo            DECIMAL(5,2) NULL COMMENT 'Horas ausentes / horas dictadas; NULL si aun no hay horas dictadas',
  definitiva                  TINYINT(1) NOT NULL DEFAULT 0 COMMENT '0 = provisional; 1 = definitiva al cerrar el corte (RF-43)',
  calculada_en                DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_alertas_inscripcion_corte (inscripcion_id, corte_id),
  KEY ix_alertas_corte_estado (corte_id, estado_alerta),
  KEY ix_alertas_configuracion (configuracion_alerta_id),
  CONSTRAINT fk_alertas_inscripciones FOREIGN KEY (inscripcion_id) REFERENCES inscripciones (id)
    ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_alertas_cortes FOREIGN KEY (corte_id) REFERENCES cortes (id)
    ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_alertas_configuraciones_alerta FOREIGN KEY (configuracion_alerta_id)
    REFERENCES configuraciones_alerta (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_alertas_estado CHECK (estado_alerta IN ('verde','amarilla','roja')),
  CONSTRAINT ck_alertas_motivos CHECK (motivo_nota IN (0,1) AND motivo_inasistencia IN (0,1)),
  CONSTRAINT ck_alertas_coherencia_motivo CHECK
    ((estado_alerta = 'verde') = (motivo_nota = 0 AND motivo_inasistencia = 0)),
  CONSTRAINT ck_alertas_definitiva CHECK (definitiva IN (0,1)),
  CONSTRAINT ck_alertas_horas CHECK (horas_ausentes <= horas_totales AND horas_dictadas <= horas_totales)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_spanish_ci
  COMMENT='Resultado calculado por estudiante, curso y corte. Copia controlada de datos derivados (ver modelo-datos.md)';

CREATE OR REPLACE VIEW vw_estudiantes_riesgo_alto AS
SELECT a.corte_id,
       m.estudiante_id,
       COUNT(DISTINCT c.asignatura_id) AS asignaturas_en_alerta
FROM alertas a
JOIN inscripciones i        ON i.id = a.inscripcion_id AND i.retirada_en IS NULL
JOIN matriculas_periodo m   ON m.id = i.matricula_periodo_id
JOIN cursos c               ON c.id = i.curso_id
WHERE a.estado_alerta IN ('amarilla','roja')
GROUP BY a.corte_id, m.estudiante_id
HAVING COUNT(DISTINCT c.asignatura_id) >= 2;

-- =====================================================================
-- E7. CONTINUIDAD Y DESERCION (RF-49 a RF-53)
-- (La no continuidad se calcula; solo se guarda la causa opcional)
-- =====================================================================

CREATE TABLE IF NOT EXISTS causas_no_continuidad (
  id      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  codigo  VARCHAR(30) NOT NULL,
  nombre  VARCHAR(50) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_causas_no_continuidad_codigo (codigo),
  UNIQUE KEY uq_causas_no_continuidad_nombre (nombre)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_spanish_ci
  COMMENT='Lista fija: economica, academica, personal, laboral, otra (RF-52)';

CREATE TABLE IF NOT EXISTS registros_causa_no_continuidad (
  id                          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  matricula_periodo_id        BIGINT UNSIGNED NOT NULL COMMENT 'Participacion del estudiante en el periodo tras el cual no continuo',
  causa_no_continuidad_id     BIGINT UNSIGNED NOT NULL,
  registrado_por_usuario_id   BIGINT UNSIGNED NOT NULL,
  registrado_en               DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_registros_causa_matricula (matricula_periodo_id, id),
  KEY ix_registros_causa_causa (causa_no_continuidad_id),
  KEY ix_registros_causa_registrador (registrado_por_usuario_id),
  CONSTRAINT fk_registros_causa_matriculas FOREIGN KEY (matricula_periodo_id)
    REFERENCES matriculas_periodo (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_registros_causa_causas FOREIGN KEY (causa_no_continuidad_id)
    REFERENCES causas_no_continuidad (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_registros_causa_usuarios FOREIGN KEY (registrado_por_usuario_id)
    REFERENCES usuarios (id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_spanish_ci
  COMMENT='Causa opcional con historial: cada cambio agrega una fila; la vigente es la ultima (RF-52)';

-- =====================================================================
-- E11. BITACORA (RF-61)
-- =====================================================================

CREATE TABLE IF NOT EXISTS tipos_evento_bitacora (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  codigo       VARCHAR(40) NOT NULL,
  descripcion  VARCHAR(150) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_tipos_evento_bitacora_codigo (codigo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_spanish_ci
  COMMENT='Catalogo de eventos que se registran (RF-61)';

CREATE TABLE IF NOT EXISTS bitacora (
  id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  creado_en             DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  tipo_evento_id        BIGINT UNSIGNED NOT NULL,
  usuario_id            BIGINT UNSIGNED NULL COMMENT 'NULL = el Sistema, o un intento fallido con correo no registrado',
  entidad               VARCHAR(50) NULL COMMENT 'Nombre de la tabla afectada, sin FK a proposito: la bitacora debe sobrevivir a cualquier tabla',
  entidad_id            BIGINT UNSIGNED NULL,
  detalle               VARCHAR(1000) NULL COMMENT 'Texto breve; nunca contrasenas, tokens ni datos sensibles',
  PRIMARY KEY (id),
  KEY ix_bitacora_creado_en (creado_en),
  KEY ix_bitacora_usuario_fecha (usuario_id, creado_en),
  KEY ix_bitacora_evento_fecha (tipo_evento_id, creado_en),
  KEY ix_bitacora_entidad (entidad, entidad_id),
  CONSTRAINT fk_bitacora_tipos_evento FOREIGN KEY (tipo_evento_id) REFERENCES tipos_evento_bitacora (id)
    ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_bitacora_usuarios FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
    ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_spanish_ci
  COMMENT='Registro inmutable de eventos con usuario, accion, objeto y fecha-hora (RF-61)';

-- =====================================================================
-- TRIGGERS: tablas de solo-insercion (RF-61, RF-31, RF-33, RF-32)
-- La bitacora y los historiales no pueden modificarse ni eliminarse,
-- ni siquiera por error de la aplicacion.
-- =====================================================================

DELIMITER $$

CREATE TRIGGER IF NOT EXISTS tg_bitacora_no_actualizar BEFORE UPDATE ON bitacora
FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'La bitacora es de solo insercion (RF-61)';
END$$

CREATE TRIGGER IF NOT EXISTS tg_bitacora_no_eliminar BEFORE DELETE ON bitacora
FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'La bitacora es de solo insercion (RF-61)';
END$$

CREATE TRIGGER IF NOT EXISTS tg_historial_notas_no_actualizar BEFORE UPDATE ON historial_notas
FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'El historial de notas es de solo insercion (RF-33)';
END$$

CREATE TRIGGER IF NOT EXISTS tg_historial_notas_no_eliminar BEFORE DELETE ON historial_notas
FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'El historial de notas es de solo insercion (RF-33)';
END$$

CREATE TRIGGER IF NOT EXISTS tg_historial_ausencias_no_actualizar BEFORE UPDATE ON historial_ausencias
FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'El historial de asistencia es de solo insercion (RF-33)';
END$$

CREATE TRIGGER IF NOT EXISTS tg_historial_ausencias_no_eliminar BEFORE DELETE ON historial_ausencias
FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'El historial de asistencia es de solo insercion (RF-33)';
END$$

DELIMITER ;
