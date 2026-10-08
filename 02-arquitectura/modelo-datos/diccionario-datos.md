# Diccionario de datos de PLASEA

Generado automáticamente a partir de la base de datos creada con `plasea_esquema.sql` (motor validado: MariaDB 10.11). Fuente de verdad: el script SQL; si cambia, se regenera este archivo.

Convenciones: PK = `id` (BIGINT UNSIGNED autoincremental); FK = `<entidad>_id` o `<rol>_usuario_id`; fechas y horas en hora de Colombia (UTC-5).

## `alertas`

Resultado calculado por estudiante, curso y corte. Copia controlada de datos derivados (ver modelo-datos.md)

| Columna | Tipo | Nulo | Defecto | Clave | Descripción |
|---|---|---|---|---|---|
| `id` | bigint(20) unsigned | No | NULL | PK |  |
| `inscripcion_id` | bigint(20) unsigned | No | NULL | IX |  |
| `corte_id` | bigint(20) unsigned | No | NULL | IX |  |
| `configuracion_alerta_id` | bigint(20) unsigned | No | NULL | IX | Version de umbrales con la que se calculo (RF-20) |
| `estado_alerta` | varchar(10) | No | NULL |  | verde \| amarilla \| roja (RF-43) |
| `motivo_nota` | tinyint(1) | No | 0 |  |  |
| `motivo_inasistencia` | tinyint(1) | No | 0 |  |  |
| `nota_corte` | decimal(2,1) | Sí | NULL |  | NULL si el estudiante no tiene nota en el corte |
| `nota_acumulada` | decimal(4,2) | Sí | NULL |  | RF-40: puede tener hasta dos decimales |
| `nota_requerida` | decimal(5,2) | Sí | NULL |  | RF-41: puede superar 5,0 (asignatura perdida por nota); NULL tras el ultimo corte |
| `horas_ausentes` | smallint(5) unsigned | No | 0 |  |  |
| `horas_dictadas` | smallint(5) unsigned | No | 0 |  |  |
| `horas_totales` | smallint(5) unsigned | No | 0 |  |  |
| `porcentaje_inasistencia` | decimal(5,2) | No | 0.00 |  | Horas ausentes / horas totales (RF-42) |
| `porcentaje_ritmo` | decimal(5,2) | Sí | NULL |  | Horas ausentes / horas dictadas; NULL si aun no hay horas dictadas |
| `definitiva` | tinyint(1) | No | 0 |  | 0 = provisional; 1 = definitiva al cerrar el corte (RF-43) |
| `calculada_en` | datetime | No | current_timestamp() |  |  |

## `asignaturas`

Asignaturas (sinonimo de materias) - RF-13

| Columna | Tipo | Nulo | Defecto | Clave | Descripción |
|---|---|---|---|---|---|
| `id` | bigint(20) unsigned | No | NULL | PK |  |
| `codigo` | varchar(20) | No | NULL | UQ |  |
| `nombre` | varchar(150) | No | NULL |  |  |
| `programa_academico_id` | bigint(20) unsigned | No | NULL | IX |  |
| `creditos` | tinyint(3) unsigned | No | NULL |  | 3 o 4 |
| `horas_semanales` | tinyint(3) unsigned | No | NULL |  |  |
| `nivel` | tinyint(3) unsigned | No | NULL |  | Nivel de la carrera, 1 a 10 |
| `creado_en` | datetime | No | current_timestamp() |  |  |
| `actualizado_en` | datetime | No | current_timestamp() |  |  |

## `ausencias`

Solo se guardan los ausentes; quien no tiene fila estuvo presente (RF-28)

| Columna | Tipo | Nulo | Defecto | Clave | Descripción |
|---|---|---|---|---|---|
| `id` | bigint(20) unsigned | No | NULL | PK |  |
| `sesion_clase_id` | bigint(20) unsigned | No | NULL | IX |  |
| `inscripcion_id` | bigint(20) unsigned | No | NULL | IX |  |
| `ausente` | tinyint(1) | No | 1 |  | 1 = ausente; 0 = ausencia corregida (la fila no se elimina) |
| `registrada_por_usuario_id` | bigint(20) unsigned | No | NULL | IX |  |
| `creado_en` | datetime | No | current_timestamp() |  |  |
| `actualizado_en` | datetime | No | current_timestamp() |  |  |

## `bitacora`

Registro inmutable de eventos con usuario, accion, objeto y fecha-hora (RF-61)

| Columna | Tipo | Nulo | Defecto | Clave | Descripción |
|---|---|---|---|---|---|
| `id` | bigint(20) unsigned | No | NULL | PK |  |
| `creado_en` | datetime(3) | No | current_timestamp(3) | IX |  |
| `tipo_evento_id` | bigint(20) unsigned | No | NULL | IX |  |
| `usuario_id` | bigint(20) unsigned | Sí | NULL | IX | NULL = el Sistema, o un intento fallido con correo no registrado |
| `entidad` | varchar(50) | Sí | NULL | IX | Nombre de la tabla afectada, sin FK a proposito: la bitacora debe sobrevivir a cualquier tabla |
| `entidad_id` | bigint(20) unsigned | Sí | NULL |  |  |
| `detalle` | varchar(1000) | Sí | NULL |  | Texto breve; nunca contrasenas, tokens ni datos sensibles |

## `bloques_horario`

Horario semanal del curso: sesiones de 1, 2 o 3 horas (RF-15). El traslape lo valida la aplicacion

| Columna | Tipo | Nulo | Defecto | Clave | Descripción |
|---|---|---|---|---|---|
| `id` | bigint(20) unsigned | No | NULL | PK |  |
| `curso_id` | bigint(20) unsigned | No | NULL | IX |  |
| `dia_semana` | tinyint(3) unsigned | No | NULL |  | 1 = lunes ... 7 = domingo (ISO 8601) |
| `hora_inicio` | time | No | NULL |  |  |
| `hora_fin` | time | No | NULL |  |  |

## `causas_no_continuidad`

Lista fija: economica, academica, personal, laboral, otra (RF-52)

| Columna | Tipo | Nulo | Defecto | Clave | Descripción |
|---|---|---|---|---|---|
| `id` | bigint(20) unsigned | No | NULL | PK |  |
| `codigo` | varchar(30) | No | NULL | UQ |  |
| `nombre` | varchar(50) | No | NULL | UQ |  |

## `configuraciones_alerta`

Umbrales de alerta versionados: cada cambio es una fila nueva; la vigente es la mas reciente (RF-20)

| Columna | Tipo | Nulo | Defecto | Clave | Descripción |
|---|---|---|---|---|---|
| `id` | bigint(20) unsigned | No | NULL | PK |  |
| `nota_aprobacion` | decimal(2,1) | No | 3.0 |  |  |
| `limite_perdida_inasistencia` | decimal(5,2) | No | 30.00 |  | Porcentaje; se pierde al superarlo |
| `umbral_amarillo_inasistencia` | decimal(5,2) | No | 20.00 |  | Porcentaje; tambien aplica al ritmo de inasistencia |
| `nota_amarilla_minima` | decimal(2,1) | No | 3.0 |  |  |
| `nota_amarilla_maxima` | decimal(2,1) | No | 3.4 |  |  |
| `vigente_desde` | datetime | No | current_timestamp() | IX |  |
| `creado_por_usuario_id` | bigint(20) unsigned | Sí | NULL | IX | NULL = configuracion inicial del sistema |

## `cortes`

Los 3 cortes de cada periodo con pesos, plazos y estado de cierre (RF-17, RF-36, RF-37)

| Columna | Tipo | Nulo | Defecto | Clave | Descripción |
|---|---|---|---|---|---|
| `id` | bigint(20) unsigned | No | NULL | PK |  |
| `periodo_academico_id` | bigint(20) unsigned | No | NULL | IX |  |
| `numero` | tinyint(3) unsigned | No | NULL |  | 1, 2 o 3 |
| `peso_porcentaje` | decimal(5,2) | No | NULL |  | Por defecto 30, 30 y 40; la suma de 100 la valida la aplicacion (RF-17) |
| `fecha_inicio` | date | No | NULL |  |  |
| `fecha_fin` | date | No | NULL |  |  |
| `limite_carga` | date | No | NULL |  |  |
| `limite_correccion` | date | No | NULL |  |  |
| `cerrado_en` | datetime | Sí | NULL |  | NULL = corte abierto |
| `tipo_cierre` | varchar(10) | Sí | NULL |  | manual (RF-36) \| automatico (RF-37) |
| `cerrado_por_usuario_id` | bigint(20) unsigned | Sí | NULL | IX | Auditor que cerro; NULL si fue automatico |
| `aviso_resumen_enviado_en` | datetime | Sí | NULL |  | Garantiza un solo correo de resumen por corte cerrado (RF-57) |
| `creado_en` | datetime | No | current_timestamp() |  |  |
| `actualizado_en` | datetime | No | current_timestamp() |  |  |

## `cursos`

Cursos de una asignatura en un periodo, con su docente (RF-14)

| Columna | Tipo | Nulo | Defecto | Clave | Descripción |
|---|---|---|---|---|---|
| `id` | bigint(20) unsigned | No | NULL | PK |  |
| `asignatura_id` | bigint(20) unsigned | No | NULL | IX |  |
| `periodo_academico_id` | bigint(20) unsigned | No | NULL | IX |  |
| `codigo` | varchar(10) | No | NULL |  | Ejemplo: T01, T02 |
| `profesor_usuario_id` | bigint(20) unsigned | No | NULL | IX | Un solo docente por curso; la aplicacion exige rol Profesor (RF-14) |
| `creado_en` | datetime | No | current_timestamp() |  |  |
| `actualizado_en` | datetime | No | current_timestamp() |  |  |

## `estados_estudiante`

Catalogo: activo, graduado, retirado formal, aplazo semestre, cancelado (RF-22)

| Columna | Tipo | Nulo | Defecto | Clave | Descripción |
|---|---|---|---|---|---|
| `id` | bigint(20) unsigned | No | NULL | PK |  |
| `codigo` | varchar(30) | No | NULL | UQ |  |
| `nombre` | varchar(50) | No | NULL | UQ |  |

## `estudiantes`

Estudiantes. Nunca se eliminan: su situacion se maneja con el historial de estados (RF-21)

| Columna | Tipo | Nulo | Defecto | Clave | Descripción |
|---|---|---|---|---|---|
| `id` | bigint(20) unsigned | No | NULL | PK |  |
| `codigo` | varchar(20) | No | NULL | UQ | Codigo estudiantil: identificacion del estudiante en PLASEA |
| `nombres` | varchar(150) | No | NULL | IX |  |
| `correo` | varchar(254) | No | NULL |  |  |
| `programa_academico_id` | bigint(20) unsigned | No | NULL | IX |  |
| `periodo_ingreso` | varchar(6) | No | NULL | IX | Cohorte (ejemplo 2022-1). Texto y no FK: puede ser anterior a los periodos registrados |
| `creado_en` | datetime | No | current_timestamp() |  |  |
| `actualizado_en` | datetime | No | current_timestamp() |  |  |

## `festivos`

Festivos del periodo; no hay sesiones esos dias (RF-18, RF-19)

| Columna | Tipo | Nulo | Defecto | Clave | Descripción |
|---|---|---|---|---|---|
| `id` | bigint(20) unsigned | No | NULL | PK |  |
| `periodo_academico_id` | bigint(20) unsigned | No | NULL | IX |  |
| `fecha` | date | No | NULL |  |  |

## `historial_ausencias`

Correcciones de asistencia (RF-31, RF-33). Inmutable

| Columna | Tipo | Nulo | Defecto | Clave | Descripción |
|---|---|---|---|---|---|
| `id` | bigint(20) unsigned | No | NULL | PK |  |
| `ausencia_id` | bigint(20) unsigned | No | NULL | IX |  |
| `ausente_anterior` | tinyint(1) | No | NULL |  |  |
| `ausente_nuevo` | tinyint(1) | No | NULL |  |  |
| `motivo` | varchar(500) | No | NULL |  |  |
| `usuario_id` | bigint(20) unsigned | No | NULL | IX |  |
| `reapertura_curso_id` | bigint(20) unsigned | Sí | NULL | IX |  |
| `creado_en` | datetime | No | current_timestamp() | IX |  |

## `historial_estados_estudiante`

Historial de estados del estudiante; el estado actual es el de fecha_efectiva mas reciente (RF-22)

| Columna | Tipo | Nulo | Defecto | Clave | Descripción |
|---|---|---|---|---|---|
| `id` | bigint(20) unsigned | No | NULL | PK |  |
| `estudiante_id` | bigint(20) unsigned | No | NULL | IX |  |
| `estado_estudiante_id` | bigint(20) unsigned | No | NULL | IX |  |
| `fecha_efectiva` | date | No | NULL |  |  |
| `registrado_por_usuario_id` | bigint(20) unsigned | No | NULL | IX |  |
| `creado_en` | datetime | No | current_timestamp() |  |  |

## `historial_notas`

Correcciones de notas: valor anterior, nuevo, motivo, usuario y fecha (RF-31, RF-33). Inmutable

| Columna | Tipo | Nulo | Defecto | Clave | Descripción |
|---|---|---|---|---|---|
| `id` | bigint(20) unsigned | No | NULL | PK |  |
| `nota_corte_id` | bigint(20) unsigned | No | NULL | IX |  |
| `nota_anterior` | decimal(2,1) | No | NULL |  |  |
| `nota_nueva` | decimal(2,1) | No | NULL |  |  |
| `motivo` | varchar(500) | No | NULL |  |  |
| `usuario_id` | bigint(20) unsigned | No | NULL | IX |  |
| `reapertura_curso_id` | bigint(20) unsigned | Sí | NULL | IX | Si la correccion se hizo en una reapertura excepcional (RF-38) |
| `creado_en` | datetime | No | current_timestamp() | IX |  |

## `inscripciones`

Inscripcion de un estudiante (via su matricula del periodo) en un curso (RF-23)

| Columna | Tipo | Nulo | Defecto | Clave | Descripción |
|---|---|---|---|---|---|
| `id` | bigint(20) unsigned | No | NULL | PK |  |
| `matricula_periodo_id` | bigint(20) unsigned | No | NULL | IX |  |
| `curso_id` | bigint(20) unsigned | No | NULL | IX |  |
| `periodo_academico_id` | bigint(20) unsigned | No | NULL |  | Columna de consistencia: matricula y curso deben ser del mismo periodo |
| `retirada_en` | date | Sí | NULL |  | Retiro del curso; la fila se conserva (RF-23) |
| `creado_en` | datetime | No | current_timestamp() |  |  |
| `actualizado_en` | datetime | No | current_timestamp() |  |  |

## `matriculas_periodo`

Participacion de un estudiante en un periodo con su semestre cursado: base de RF-49 a RF-53

| Columna | Tipo | Nulo | Defecto | Clave | Descripción |
|---|---|---|---|---|---|
| `id` | bigint(20) unsigned | No | NULL | PK |  |
| `estudiante_id` | bigint(20) unsigned | No | NULL | IX |  |
| `periodo_academico_id` | bigint(20) unsigned | No | NULL | IX |  |
| `semestre_cursado` | tinyint(3) unsigned | No | NULL |  | Semestre de la carrera que cursa en el periodo, 1 a 10 (RF-23, RF-51) |
| `creado_en` | datetime | No | current_timestamp() |  |  |
| `actualizado_en` | datetime | No | current_timestamp() |  |  |

## `notas_corte`

Nota consolidada de un estudiante en un corte; la fila existe solo si hay nota (RF-29)

| Columna | Tipo | Nulo | Defecto | Clave | Descripción |
|---|---|---|---|---|---|
| `id` | bigint(20) unsigned | No | NULL | PK |  |
| `inscripcion_id` | bigint(20) unsigned | No | NULL | IX |  |
| `corte_id` | bigint(20) unsigned | No | NULL | IX |  |
| `nota` | decimal(2,1) | No | NULL |  | Escala 1,0 a 5,0 con un decimal (RF-29) |
| `registrada_por_usuario_id` | bigint(20) unsigned | No | NULL | IX |  |
| `creado_en` | datetime | No | current_timestamp() |  |  |
| `actualizado_en` | datetime | No | current_timestamp() |  |  |

## `periodos_academicos`

Semestres academicos (RF-16). El orden cronologico lo da fecha_inicio

| Columna | Tipo | Nulo | Defecto | Clave | Descripción |
|---|---|---|---|---|---|
| `id` | bigint(20) unsigned | No | NULL | PK |  |
| `identificador` | varchar(6) | No | NULL | UQ | Ejemplo: 2026-2 |
| `fecha_inicio` | date | No | NULL | IX |  |
| `fecha_fin` | date | No | NULL |  | Fin de las 16 semanas; la duracion exacta la valida la aplicacion |
| `en_curso_marca` | tinyint(4) | Sí | NULL | UQ | 1 = periodo en curso; NULL = no. UNIQUE garantiza uno solo (RF-16) |
| `creado_en` | datetime | No | current_timestamp() |  |  |
| `actualizado_en` | datetime | No | current_timestamp() |  |  |

## `programas_academicos`

Catalogo de programas (hoy solo Ingenieria de Sistemas; RF-13, RF-21, RF-53)

| Columna | Tipo | Nulo | Defecto | Clave | Descripción |
|---|---|---|---|---|---|
| `id` | bigint(20) unsigned | No | NULL | PK |  |
| `nombre` | varchar(100) | No | NULL | UQ |  |

## `reaperturas_curso`

Reaperturas excepcionales por curso y corte, con motivo obligatorio (RF-38, RF-39)

| Columna | Tipo | Nulo | Defecto | Clave | Descripción |
|---|---|---|---|---|---|
| `id` | bigint(20) unsigned | No | NULL | PK |  |
| `registro_curso_corte_id` | bigint(20) unsigned | No | NULL | IX |  |
| `motivo` | varchar(500) | No | NULL |  |  |
| `abierta_por_usuario_id` | bigint(20) unsigned | No | NULL | IX |  |
| `abierta_en` | datetime | No | current_timestamp() |  |  |
| `cerrada_por_usuario_id` | bigint(20) unsigned | Sí | NULL | IX |  |
| `cerrada_en` | datetime | Sí | NULL |  | NULL = reapertura vigente (RF-39) |
| `vigente_marca` | tinyint(4) (calculada) | Sí | NULL |  | Calculada: 1 si vigente. UNIQUE garantiza una sola reapertura vigente por registro |

## `registros_causa_no_continuidad`

Causa opcional con historial: cada cambio agrega una fila; la vigente es la ultima (RF-52)

| Columna | Tipo | Nulo | Defecto | Clave | Descripción |
|---|---|---|---|---|---|
| `id` | bigint(20) unsigned | No | NULL | PK |  |
| `matricula_periodo_id` | bigint(20) unsigned | No | NULL | IX | Participacion del estudiante en el periodo tras el cual no continuo |
| `causa_no_continuidad_id` | bigint(20) unsigned | No | NULL | IX |  |
| `registrado_por_usuario_id` | bigint(20) unsigned | No | NULL | IX |  |
| `registrado_en` | datetime | No | current_timestamp() |  |  |

## `registros_curso_corte`

Estado del registro de un curso en un corte: borrador a envio a cierre (RF-26, RF-30, RF-35, RF-36)

| Columna | Tipo | Nulo | Defecto | Clave | Descripción |
|---|---|---|---|---|---|
| `id` | bigint(20) unsigned | No | NULL | PK |  |
| `curso_id` | bigint(20) unsigned | No | NULL | IX |  |
| `corte_id` | bigint(20) unsigned | No | NULL | IX |  |
| `estado` | varchar(15) | No | 'pendiente' |  | pendiente \| enviado \| cerrado \| sin_registro |
| `enviado_en` | datetime | Sí | NULL |  |  |
| `enviado_por_usuario_id` | bigint(20) unsigned | Sí | NULL | IX |  |
| `creado_en` | datetime | No | current_timestamp() |  |  |
| `actualizado_en` | datetime | No | current_timestamp() |  |  |

## `roles`

Catalogo de los 3 roles fijos (RF-02)

| Columna | Tipo | Nulo | Defecto | Clave | Descripción |
|---|---|---|---|---|---|
| `id` | bigint(20) unsigned | No | NULL | PK |  |
| `codigo` | varchar(30) | No | NULL | UQ | Identificador estable usado por la aplicacion |
| `nombre` | varchar(50) | No | NULL | UQ | Nombre para mostrar |

## `sesiones_clase`

Calendario de sesiones de cada curso, generado desde horario, periodo y festivos (RF-19)

| Columna | Tipo | Nulo | Defecto | Clave | Descripción |
|---|---|---|---|---|---|
| `id` | bigint(20) unsigned | No | NULL | PK |  |
| `curso_id` | bigint(20) unsigned | No | NULL | IX |  |
| `fecha` | date | No | NULL |  |  |
| `hora_inicio` | time | No | NULL |  |  |
| `hora_fin` | time | No | NULL |  |  |
| `duracion_horas` | tinyint(3) unsigned (calculada) | Sí | NULL |  | Calculada: horas que se cargan a cada ausente (RF-28) |
| `asistencia_registrada_en` | datetime | Sí | NULL |  | Marca que el profesor registro la asistencia, aunque no haya ausentes (RF-30) |
| `asistencia_registrada_por_usuario_id` | bigint(20) unsigned | Sí | NULL | IX |  |

## `sesiones_usuario`

Sesiones en el servidor: permiten cerrar, expirar e invalidar sesiones (RF-03, RF-04, RF-07, RF-11)

| Columna | Tipo | Nulo | Defecto | Clave | Descripción |
|---|---|---|---|---|---|
| `id` | bigint(20) unsigned | No | NULL | PK |  |
| `usuario_id` | bigint(20) unsigned | No | NULL | IX |  |
| `rol_id` | bigint(20) unsigned | No | NULL | IX | Rol vigente al iniciar sesion: un cambio de rol aplica desde el siguiente inicio (RF-10) |
| `token_hash` | char(64) | No | NULL | UQ | SHA-256 del identificador opaco guardado en la cookie de sesion |
| `creada_en` | datetime | No | current_timestamp() |  |  |
| `ultima_actividad_en` | datetime | No | current_timestamp() |  | Base de la expiracion por inactividad (RF-04) |
| `cerrada_en` | datetime | Sí | NULL |  |  |
| `motivo_cierre` | varchar(40) | Sí | NULL |  |  |

## `tipos_evento_bitacora`

Catalogo de eventos que se registran (RF-61)

| Columna | Tipo | Nulo | Defecto | Clave | Descripción |
|---|---|---|---|---|---|
| `id` | bigint(20) unsigned | No | NULL | PK |  |
| `codigo` | varchar(40) | No | NULL | UQ |  |
| `descripcion` | varchar(150) | No | NULL |  |  |

## `tokens_cuenta`

Enlaces de un solo uso para activar cuenta y restablecer contrasena

| Columna | Tipo | Nulo | Defecto | Clave | Descripción |
|---|---|---|---|---|---|
| `id` | bigint(20) unsigned | No | NULL | PK |  |
| `usuario_id` | bigint(20) unsigned | No | NULL | IX |  |
| `proposito` | varchar(20) | No | NULL |  | activacion (RF-08/09) \| restablecimiento (RF-06/07) |
| `token_hash` | char(64) | No | NULL | UQ | SHA-256 en hexadecimal del token enviado por correo; el token nunca se guarda |
| `creado_en` | datetime | No | current_timestamp() |  |  |
| `vence_en` | datetime | No | NULL |  | Vigencia parametrizable en el archivo de configuracion |
| `usado_en` | datetime | Sí | NULL |  | Uso unico: se llena al consumir el enlace |
| `invalidado_en` | datetime | Sí | NULL |  | Se llena cuando un enlace nuevo o un cambio de estado lo reemplaza |

## `usuarios`

Cuentas de usuario. Nunca se eliminan, solo se desactivan (RF-11)

| Columna | Tipo | Nulo | Defecto | Clave | Descripción |
|---|---|---|---|---|---|
| `id` | bigint(20) unsigned | No | NULL | PK |  |
| `nombre_completo` | varchar(150) | No | NULL | IX |  |
| `correo` | varchar(254) | No | NULL | UQ | Correo institucional, unico sin distinguir mayusculas (RF-08) |
| `contrasena_hash` | varchar(255) | Sí | NULL |  | Solo el hash producido por la aplicacion; NULL mientras la cuenta esta pendiente de activacion |
| `rol_id` | bigint(20) unsigned | No | NULL | IX |  |
| `estado_cuenta` | varchar(25) | No | 'pendiente_activacion' |  | pendiente_activacion \| activa \| inactiva \| bloqueada (bloqueo administrativo, RF-11) |
| `intentos_fallidos` | tinyint(3) unsigned | No | 0 |  | Intentos consecutivos fallidos (RF-05) |
| `bloqueo_hasta` | datetime | Sí | NULL |  | Bloqueo temporal automatico por intentos fallidos (RF-05); NULL si no hay |
| `creado_en` | datetime | No | current_timestamp() |  |  |
| `actualizado_en` | datetime | No | current_timestamp() |  |  |
