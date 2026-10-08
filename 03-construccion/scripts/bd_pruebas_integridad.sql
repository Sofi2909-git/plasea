-- =====================================================================
-- PLASEA - Pruebas de integridad de la base de datos
-- Ruta: 03-construccion/scripts/bd_pruebas_integridad.sql
-- =====================================================================
SET NAMES utf8mb4;
USE plasea;

DROP TEMPORARY TABLE IF EXISTS tmp_resultados;
CREATE TEMPORARY TABLE tmp_resultados (
  n INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  grupo VARCHAR(20), prueba VARCHAR(110), esperado VARCHAR(12), resultado VARCHAR(10), detalle VARCHAR(150)
) ENGINE=MEMORY;

DROP PROCEDURE IF EXISTS tmp_debe_fallar;
DROP PROCEDURE IF EXISTS tmp_debe_funcionar;
DELIMITER $$

CREATE PROCEDURE tmp_debe_fallar(IN p_grupo VARCHAR(20), IN p_prueba VARCHAR(110), IN p_sql TEXT)
BEGIN
  DECLARE v_fallo INT DEFAULT 0;
  DECLARE v_msg TEXT DEFAULT '';
  DECLARE CONTINUE HANDLER FOR SQLEXCEPTION
    BEGIN GET DIAGNOSTICS CONDITION 1 v_msg = MESSAGE_TEXT; SET v_fallo = 1; END;
  SET @tmp_sql = p_sql;
  PREPARE st FROM @tmp_sql;
  EXECUTE st;
  DEALLOCATE PREPARE st;
  INSERT INTO tmp_resultados (grupo, prueba, esperado, resultado, detalle)
  VALUES (p_grupo, p_prueba, 'rechazo', IF(v_fallo = 1, 'APROBADA', 'FALLIDA'), LEFT(v_msg, 150));
END$$

CREATE PROCEDURE tmp_debe_funcionar(IN p_grupo VARCHAR(20), IN p_prueba VARCHAR(110), IN p_sql TEXT)
BEGIN
  DECLARE v_fallo INT DEFAULT 0;
  DECLARE v_msg TEXT DEFAULT '';
  DECLARE CONTINUE HANDLER FOR SQLEXCEPTION
    BEGIN GET DIAGNOSTICS CONDITION 1 v_msg = MESSAGE_TEXT; SET v_fallo = 1; END;
  SET @tmp_sql = p_sql;
  PREPARE st FROM @tmp_sql;
  EXECUTE st;
  DEALLOCATE PREPARE st;
  INSERT INTO tmp_resultados (grupo, prueba, esperado, resultado, detalle)
  VALUES (p_grupo, p_prueba, 'aceptacion', IF(v_fallo = 0, 'APROBADA', 'FALLIDA'), LEFT(v_msg, 150));
END$$

DELIMITER ;

START TRANSACTION;

-- ---------------------------------------------------------------- datos de prueba (se revierten)
SET @rol_prof = (SELECT id FROM roles WHERE codigo = 'profesor');
SET @rol_aud  = (SELECT id FROM roles WHERE codigo = 'auditor_academico');
SET @rol_adm  = (SELECT id FROM roles WHERE codigo = 'administrador_sistema');
SET @programa = (SELECT id FROM programas_academicos LIMIT 1);
SET @config   = (SELECT id FROM configuraciones_alerta ORDER BY id LIMIT 1);
SET @ev       = (SELECT id FROM tipos_evento_bitacora LIMIT 1);
SET @est_act  = (SELECT id FROM estados_estudiante WHERE codigo = 'activo');

INSERT INTO usuarios (nombre_completo, correo, contrasena_hash, rol_id, estado_cuenta)
VALUES ('Profesor Prueba', 'profe.prueba@ejemplo.test', 'hash-de-prueba', @rol_prof, 'activa');
SET @u_prof = LAST_INSERT_ID();
INSERT INTO usuarios (nombre_completo, correo, contrasena_hash, rol_id, estado_cuenta)
VALUES ('José Auditor', 'auditor.prueba@ejemplo.test', 'hash-de-prueba', @rol_aud, 'activa');
SET @u_aud = LAST_INSERT_ID();

INSERT INTO asignaturas (codigo, nombre, programa_academico_id, creditos, horas_semanales, nivel)
VALUES ('PRB-101', 'Asignatura de prueba 1', @programa, 3, 4, 5);
SET @asig1 = LAST_INSERT_ID();
INSERT INTO asignaturas (codigo, nombre, programa_academico_id, creditos, horas_semanales, nivel)
VALUES ('PRB-102', 'Asignatura de prueba 2', @programa, 4, 4, 5);
SET @asig2 = LAST_INSERT_ID();

INSERT INTO periodos_academicos (identificador, fecha_inicio, fecha_fin, en_curso_marca)
VALUES ('2090-1', '2090-02-01', '2090-05-23', 1);
SET @per1 = LAST_INSERT_ID();
INSERT INTO periodos_academicos (identificador, fecha_inicio, fecha_fin)
VALUES ('2090-2', '2090-08-01', '2090-11-21');
SET @per2 = LAST_INSERT_ID();

INSERT INTO cortes (periodo_academico_id, numero, peso_porcentaje, fecha_inicio, fecha_fin, limite_carga, limite_correccion)
VALUES (@per1, 1, 30, '2090-02-01', '2090-03-07', '2090-03-14', '2090-03-21');
SET @corte1 = LAST_INSERT_ID();

INSERT INTO cursos (asignatura_id, periodo_academico_id, codigo, profesor_usuario_id) VALUES (@asig1, @per1, 'T01', @u_prof);
SET @curso1 = LAST_INSERT_ID();
INSERT INTO cursos (asignatura_id, periodo_academico_id, codigo, profesor_usuario_id) VALUES (@asig2, @per1, 'T01', @u_prof);
SET @curso2 = LAST_INSERT_ID();
INSERT INTO cursos (asignatura_id, periodo_academico_id, codigo, profesor_usuario_id) VALUES (@asig1, @per2, 'T01', @u_prof);
SET @curso_otro_periodo = LAST_INSERT_ID();

INSERT INTO estudiantes (codigo, nombres, correo, programa_academico_id, periodo_ingreso)
VALUES ('E-0001', 'José Pérez Núñez', 'jose.perez@ejemplo.test', @programa, '2088-1');
SET @est = LAST_INSERT_ID();
INSERT INTO matriculas_periodo (estudiante_id, periodo_academico_id, semestre_cursado) VALUES (@est, @per1, 5);
SET @mat = LAST_INSERT_ID();
INSERT INTO inscripciones (matricula_periodo_id, curso_id, periodo_academico_id) VALUES (@mat, @curso1, @per1);
SET @insc1 = LAST_INSERT_ID();
INSERT INTO inscripciones (matricula_periodo_id, curso_id, periodo_academico_id) VALUES (@mat, @curso2, @per1);
SET @insc2 = LAST_INSERT_ID();

INSERT INTO notas_corte (inscripcion_id, corte_id, nota, registrada_por_usuario_id) VALUES (@insc1, @corte1, 3.2, @u_prof);
SET @nota1 = LAST_INSERT_ID();
INSERT INTO sesiones_clase (curso_id, fecha, hora_inicio, hora_fin) VALUES (@curso1, '2090-02-05', '08:00', '10:00');
SET @ses1 = LAST_INSERT_ID();
INSERT INTO registros_curso_corte (curso_id, corte_id) VALUES (@curso1, @corte1);
SET @reg1 = LAST_INSERT_ID();
INSERT INTO ausencias (sesion_clase_id, inscripcion_id, registrada_por_usuario_id) VALUES (@ses1, @insc1, @u_prof);
SET @aus1 = LAST_INSERT_ID();
INSERT INTO historial_notas (nota_corte_id, nota_anterior, nota_nueva, motivo, usuario_id) VALUES (@nota1, 3.0, 3.2, 'Correccion de prueba', @u_prof);
INSERT INTO historial_ausencias (ausencia_id, ausente_anterior, ausente_nuevo, motivo, usuario_id) VALUES (@aus1, 0, 1, 'Correccion de prueba', @u_prof);
INSERT INTO bitacora (tipo_evento_id, usuario_id, detalle) VALUES (@ev, @u_prof, 'evento de prueba');
INSERT INTO reaperturas_curso (registro_curso_corte_id, motivo, abierta_por_usuario_id) VALUES (@reg1, 'Falla tecnica de prueba', @u_aud);
SET @reap1 = LAST_INSERT_ID();

-- ---------------------------------------------------------------- 1. UNICIDAD (UNIQUE)
CALL tmp_debe_fallar('UNIQUE', 'Correo de usuario repetido (sin distinguir mayusculas)',
  "INSERT INTO usuarios (nombre_completo, correo, rol_id) VALUES ('Otro', 'PROFE.PRUEBA@EJEMPLO.TEST', @rol_prof)");
CALL tmp_debe_fallar('UNIQUE', 'Codigo de asignatura repetido',
  "INSERT INTO asignaturas (codigo, nombre, programa_academico_id, creditos, horas_semanales, nivel) VALUES ('prb-101','Repetida',@programa,3,4,5)");
CALL tmp_debe_fallar('UNIQUE', 'Codigo de estudiante repetido',
  "INSERT INTO estudiantes (codigo, nombres, correo, programa_academico_id, periodo_ingreso) VALUES ('E-0001','Repetido','r@ejemplo.test',@programa,'2088-1')");
CALL tmp_debe_fallar('UNIQUE', 'Dos periodos en curso a la vez',
  "UPDATE periodos_academicos SET en_curso_marca = 1 WHERE id = @per2");
CALL tmp_debe_fallar('UNIQUE', 'Curso repetido (asignatura, periodo, codigo)',
  "INSERT INTO cursos (asignatura_id, periodo_academico_id, codigo, profesor_usuario_id) VALUES (@asig1, @per1, 'T01', @u_prof)");
CALL tmp_debe_fallar('UNIQUE', 'Inscripcion repetida en el mismo curso',
  "INSERT INTO inscripciones (matricula_periodo_id, curso_id, periodo_academico_id) VALUES (@mat, @curso1, @per1)");
CALL tmp_debe_fallar('UNIQUE', 'Segunda nota para el mismo estudiante y corte',
  "INSERT INTO notas_corte (inscripcion_id, corte_id, nota, registrada_por_usuario_id) VALUES (@insc1, @corte1, 4.0, @u_prof)");
CALL tmp_debe_fallar('UNIQUE', 'Segunda matricula del estudiante en el mismo periodo',
  "INSERT INTO matriculas_periodo (estudiante_id, periodo_academico_id, semestre_cursado) VALUES (@est, @per1, 6)");
CALL tmp_debe_fallar('UNIQUE', 'Segunda reapertura vigente del mismo registro',
  "INSERT INTO reaperturas_curso (registro_curso_corte_id, motivo, abierta_por_usuario_id) VALUES (@reg1, 'Otra', @u_aud)");
CALL tmp_debe_fallar('UNIQUE', 'Segunda fila de ausencia para la misma sesion y estudiante',
  "INSERT INTO ausencias (sesion_clase_id, inscripcion_id, registrada_por_usuario_id) VALUES (@ses1, @insc1, @u_prof)");

-- ---------------------------------------------------------------- 2. RELACIONES (FOREIGN KEY)
CALL tmp_debe_fallar('FOREIGN KEY', 'Usuario con rol inexistente',
  "INSERT INTO usuarios (nombre_completo, correo, rol_id) VALUES ('X','x@ejemplo.test', 999999)");
CALL tmp_debe_fallar('FOREIGN KEY', 'Curso con profesor inexistente',
  "INSERT INTO cursos (asignatura_id, periodo_academico_id, codigo, profesor_usuario_id) VALUES (@asig2, @per2, 'T09', 999999)");
CALL tmp_debe_fallar('FOREIGN KEY', 'Inscripcion en un curso de otro periodo que su matricula',
  "INSERT INTO inscripciones (matricula_periodo_id, curso_id, periodo_academico_id) VALUES (@mat, @curso_otro_periodo, @per1)");
CALL tmp_debe_fallar('FOREIGN KEY', 'Nota para una inscripcion inexistente',
  "INSERT INTO notas_corte (inscripcion_id, corte_id, nota, registrada_por_usuario_id) VALUES (999999, @corte1, 3.0, @u_prof)");
CALL tmp_debe_fallar('FOREIGN KEY', 'Eliminar un rol con usuarios (RESTRICT)',
  "DELETE FROM roles WHERE id = @rol_prof");
CALL tmp_debe_fallar('FOREIGN KEY', 'Eliminar un estudiante con matricula (RESTRICT)',
  "DELETE FROM estudiantes WHERE id = @est");
CALL tmp_debe_fallar('FOREIGN KEY', 'Eliminar un curso con inscripciones (RESTRICT)',
  "DELETE FROM cursos WHERE id = @curso1");
CALL tmp_debe_fallar('FOREIGN KEY', 'Eliminar una asignatura con cursos (RF-13)',
  "DELETE FROM asignaturas WHERE id = @asig1");
CALL tmp_debe_fallar('FOREIGN KEY', 'Eliminar un usuario con registros asociados',
  "DELETE FROM usuarios WHERE id = @u_prof");

-- ---------------------------------------------------------------- 3. REGLAS DE DOMINIO (CHECK / NOT NULL)
CALL tmp_debe_fallar('CHECK', 'Creditos distintos de 3 o 4',
  "INSERT INTO asignaturas (codigo, nombre, programa_academico_id, creditos, horas_semanales, nivel) VALUES ('PRB-201','X',@programa,5,4,5)");
CALL tmp_debe_fallar('CHECK', 'Nivel de la carrera fuera de 1 a 10',
  "INSERT INTO asignaturas (codigo, nombre, programa_academico_id, creditos, horas_semanales, nivel) VALUES ('PRB-202','X',@programa,3,4,11)");
CALL tmp_debe_fallar('CHECK', 'Nota mayor que 5,0',
  "UPDATE notas_corte SET nota = 5.5 WHERE id = @nota1");
CALL tmp_debe_fallar('CHECK', 'Nota menor que 1,0',
  "UPDATE notas_corte SET nota = 0.5 WHERE id = @nota1");
CALL tmp_debe_fallar('CHECK', 'Nota nula',
  "UPDATE notas_corte SET nota = NULL WHERE id = @nota1");
CALL tmp_debe_fallar('CHECK', 'Corte con numero 4',
  "INSERT INTO cortes (periodo_academico_id, numero, peso_porcentaje, fecha_inicio, fecha_fin, limite_carga, limite_correccion) VALUES (@per1, 4, 10, '2090-04-01','2090-04-30','2090-05-05','2090-05-10')");
CALL tmp_debe_fallar('CHECK', 'Limite de correccion no posterior al limite de carga',
  "INSERT INTO cortes (periodo_academico_id, numero, peso_porcentaje, fecha_inicio, fecha_fin, limite_carga, limite_correccion) VALUES (@per1, 2, 30, '2090-03-08','2090-04-11','2090-04-18','2090-04-18')");
CALL tmp_debe_fallar('CHECK', 'Cierre manual de corte sin auditor responsable',
  "UPDATE cortes SET cerrado_en = NOW(), tipo_cierre = 'manual' WHERE id = @corte1");
CALL tmp_debe_fallar('CHECK', 'Identificador de periodo con formato invalido',
  "INSERT INTO periodos_academicos (identificador, fecha_inicio, fecha_fin) VALUES ('2090-3','2091-02-01','2091-05-23')");
CALL tmp_debe_fallar('CHECK', 'Periodo cuya fecha de fin es anterior al inicio',
  "INSERT INTO periodos_academicos (identificador, fecha_inicio, fecha_fin) VALUES ('2091-1','2091-05-23','2091-02-01')");
CALL tmp_debe_fallar('CHECK', 'Bloque de horario de 4 horas',
  "INSERT INTO bloques_horario (curso_id, dia_semana, hora_inicio, hora_fin) VALUES (@curso1, 1, '07:00', '11:00')");
CALL tmp_debe_fallar('CHECK', 'Bloque de horario con fin antes del inicio',
  "INSERT INTO bloques_horario (curso_id, dia_semana, hora_inicio, hora_fin) VALUES (@curso1, 1, '10:00', '08:00')");
CALL tmp_debe_fallar('CHECK', 'Dia de la semana fuera de 1 a 7',
  "INSERT INTO bloques_horario (curso_id, dia_semana, hora_inicio, hora_fin) VALUES (@curso1, 8, '08:00', '10:00')");
CALL tmp_debe_fallar('CHECK', 'Sesion de clase de 4 horas',
  "INSERT INTO sesiones_clase (curso_id, fecha, hora_inicio, hora_fin) VALUES (@curso1, '2090-02-06', '07:00', '11:00')");
CALL tmp_debe_fallar('CHECK', 'Semestre cursado fuera de 1 a 10',
  "UPDATE matriculas_periodo SET semestre_cursado = 11 WHERE id = @mat");
CALL tmp_debe_fallar('CHECK', 'Estado de cuenta invalido',
  "UPDATE usuarios SET estado_cuenta = 'suspendida' WHERE id = @u_prof");
CALL tmp_debe_fallar('CHECK', 'Cuenta activa sin hash de contrasena',
  "UPDATE usuarios SET contrasena_hash = NULL WHERE id = @u_prof");
CALL tmp_debe_fallar('CHECK', 'Token que vence antes de crearse',
  "INSERT INTO tokens_cuenta (usuario_id, proposito, token_hash, creado_en, vence_en) VALUES (@u_prof, 'activacion', REPEAT('a',64), '2090-01-02 10:00:00', '2090-01-01 10:00:00')");
CALL tmp_debe_fallar('CHECK', 'Token que no es un SHA-256 hexadecimal',
  "INSERT INTO tokens_cuenta (usuario_id, proposito, token_hash, vence_en) VALUES (@u_prof, 'activacion', REPEAT('Z',64), NOW() + INTERVAL 1 HOUR)");
CALL tmp_debe_fallar('CHECK', 'Alerta verde con motivo de nota',
  "INSERT INTO alertas (inscripcion_id, corte_id, configuracion_alerta_id, estado_alerta, motivo_nota) VALUES (@insc2, @corte1, @config, 'verde', 1)");
CALL tmp_debe_fallar('CHECK', 'Alerta roja sin ningun motivo',
  "INSERT INTO alertas (inscripcion_id, corte_id, configuracion_alerta_id, estado_alerta) VALUES (@insc2, @corte1, @config, 'roja')");
CALL tmp_debe_fallar('CHECK', 'Estado de alerta fuera de verde, amarilla o roja',
  "INSERT INTO alertas (inscripcion_id, corte_id, configuracion_alerta_id, estado_alerta, motivo_nota) VALUES (@insc2, @corte1, @config, 'naranja', 1)");
CALL tmp_debe_fallar('CHECK', 'Umbral amarillo mayor o igual al limite de perdida',
  "INSERT INTO configuraciones_alerta (limite_perdida_inasistencia, umbral_amarillo_inasistencia) VALUES (30, 30)");
CALL tmp_debe_fallar('CHECK', 'Rango amarillo de nota invertido',
  "INSERT INTO configuraciones_alerta (nota_amarilla_minima, nota_amarilla_maxima) VALUES (3.5, 3.0)");
CALL tmp_debe_fallar('CHECK', 'Reapertura con motivo vacio',
  "INSERT INTO reaperturas_curso (registro_curso_corte_id, motivo, abierta_por_usuario_id) VALUES (@reg1, '   ', @u_aud)");
CALL tmp_debe_fallar('CHECK', 'Correccion de nota sin motivo',
  "INSERT INTO historial_notas (nota_corte_id, nota_anterior, nota_nueva, motivo, usuario_id) VALUES (@nota1, 3.2, 4.0, '', @u_prof)");
CALL tmp_debe_fallar('CHECK', 'Correccion de nota sin cambio de valor',
  "INSERT INTO historial_notas (nota_corte_id, nota_anterior, nota_nueva, motivo, usuario_id) VALUES (@nota1, 3.2, 3.2, 'igual', @u_prof)");
CALL tmp_debe_fallar('CHECK', 'Registro de curso enviado sin fecha de envio',
  "UPDATE registros_curso_corte SET estado = 'enviado' WHERE id = @reg1");
CALL tmp_debe_fallar('CHECK', 'Estudiante con periodo de ingreso invalido',
  "INSERT INTO estudiantes (codigo, nombres, correo, programa_academico_id, periodo_ingreso) VALUES ('E-0002','X','x2@ejemplo.test',@programa,'20-1')");

-- ---------------------------------------------------------------- 4. TABLAS DE SOLO INSERCION (TRIGGERS)
CALL tmp_debe_fallar('TRIGGER', 'Modificar un evento de la bitacora', "UPDATE bitacora SET detalle = 'alterado'");
CALL tmp_debe_fallar('TRIGGER', 'Eliminar un evento de la bitacora', "DELETE FROM bitacora");
CALL tmp_debe_fallar('TRIGGER', 'Modificar el historial de notas', "UPDATE historial_notas SET motivo = 'alterado'");
CALL tmp_debe_fallar('TRIGGER', 'Eliminar el historial de notas', "DELETE FROM historial_notas");
CALL tmp_debe_fallar('TRIGGER', 'Modificar el historial de asistencia', "UPDATE historial_ausencias SET motivo = 'alterado'");
CALL tmp_debe_fallar('TRIGGER', 'Eliminar el historial de asistencia', "DELETE FROM historial_ausencias");

-- ---------------------------------------------------------------- 5. OPERACIONES QUE SI DEBEN FUNCIONAR
CALL tmp_debe_funcionar('ACEPTACION', 'Nota limite 1,0 y 5,0',
  "UPDATE notas_corte SET nota = 1.0 WHERE id = @nota1");
CALL tmp_debe_funcionar('ACEPTACION', 'Nota limite 5,0',
  "UPDATE notas_corte SET nota = 5.0 WHERE id = @nota1");
CALL tmp_debe_funcionar('ACEPTACION', 'Cerrar la reapertura y abrir una nueva',
  "UPDATE reaperturas_curso SET cerrada_en = NOW(), cerrada_por_usuario_id = @u_aud WHERE id = @reap1");
CALL tmp_debe_funcionar('ACEPTACION', 'Nueva reapertura tras cerrar la anterior',
  "INSERT INTO reaperturas_curso (registro_curso_corte_id, motivo, abierta_por_usuario_id) VALUES (@reg1, 'Segunda falla tecnica', @u_aud)");
CALL tmp_debe_funcionar('ACEPTACION', 'Cierre manual de corte con auditor responsable',
  "UPDATE cortes SET cerrado_en = NOW(), tipo_cierre = 'manual', cerrado_por_usuario_id = @u_aud WHERE id = @corte1");
CALL tmp_debe_funcionar('ACEPTACION', 'Dos alertas amarillas en dos asignaturas',
  "INSERT INTO alertas (inscripcion_id, corte_id, configuracion_alerta_id, estado_alerta, motivo_nota, nota_corte) VALUES (@insc1, @corte1, @config, 'amarilla', 1, 3.2), (@insc2, @corte1, @config, 'roja', 1, 2.0)");
CALL tmp_debe_funcionar('ACEPTACION', 'Retirar al estudiante de un curso conserva la fila',
  "UPDATE inscripciones SET retirada_en = '2090-03-01' WHERE id = @insc2");
UPDATE inscripciones SET retirada_en = NULL WHERE id = @insc2;

-- ---------------------------------------------------------------- 6. COMPORTAMIENTOS CALCULADOS
INSERT INTO tmp_resultados (grupo, prueba, esperado, resultado, detalle)
SELECT 'CALCULADO', 'Duracion de la sesion de 08:00 a 10:00 = 2 horas', '2', IF(duracion_horas = 2, 'APROBADA', 'FALLIDA'), CONCAT('duracion_horas=', duracion_horas)
FROM sesiones_clase WHERE id = @ses1;

INSERT INTO tmp_resultados (grupo, prueba, esperado, resultado, detalle)
SELECT 'CALCULADO', 'Vista de riesgo alto detecta 2 asignaturas en alerta', '1 fila', IF(COUNT(*) = 1 AND MAX(asignaturas_en_alerta) = 2, 'APROBADA', 'FALLIDA'), CONCAT('filas=', COUNT(*))
FROM vw_estudiantes_riesgo_alto WHERE estudiante_id = @est;

INSERT INTO tmp_resultados (grupo, prueba, esperado, resultado, detalle)
SELECT 'CALCULADO', 'Busqueda sin tildes ni mayusculas: "jose" encuentra "José"', '2 filas', IF(COUNT(*) = 2, 'APROBADA', 'FALLIDA'), CONCAT('filas=', COUNT(*))
FROM (SELECT nombre_completo AS n FROM usuarios WHERE nombre_completo LIKE '%jose%'
      UNION ALL SELECT nombres FROM estudiantes WHERE nombres LIKE '%JOSE%') t;

INSERT INTO tmp_resultados (grupo, prueba, esperado, resultado, detalle)
SELECT 'CALCULADO', 'La "n" y la "ñ" son letras distintas en la busqueda', '0 filas', IF(COUNT(*) = 0, 'APROBADA', 'FALLIDA'), CONCAT('filas=', COUNT(*))
FROM estudiantes WHERE nombres LIKE '%nunez%';

INSERT INTO tmp_resultados (grupo, prueba, esperado, resultado, detalle)
SELECT 'DATOS', 'Los datos de prueba no contienen contrasenas reales (solo el marcador de prueba)', '0 filas',
       IF(COUNT(*) = 0, 'APROBADA', 'FALLIDA'), CONCAT('filas=', COUNT(*))
FROM usuarios WHERE contrasena_hash IS NOT NULL AND contrasena_hash <> 'hash-de-prueba';

ROLLBACK;

DROP PROCEDURE IF EXISTS tmp_debe_fallar;
DROP PROCEDURE IF EXISTS tmp_debe_funcionar;

-- ---------------------------------------------------------------- RESULTADO
SELECT n, grupo, prueba, esperado, resultado, detalle FROM tmp_resultados ORDER BY n;
SELECT resultado, COUNT(*) AS pruebas FROM tmp_resultados GROUP BY resultado;
SELECT 'Sin datos de prueba remanentes (esperado 0)' AS control,
       (SELECT COUNT(*) FROM usuarios) + (SELECT COUNT(*) FROM estudiantes) + (SELECT COUNT(*) FROM asignaturas) AS filas;
DROP TEMPORARY TABLE IF EXISTS tmp_resultados;
