"""Pruebas funcionales de RF-24 a RF-29.

Derivadas de los criterios de aceptación de REQUERIMIENTOS.txt. El escenario se
arma con fechas relativas a hoy: el período va en su semana 8, de modo que el
corte 1 está cerrado, el corte 2 tiene el plazo de carga abierto y el corte 3 no
ha iniciado. Requieren URL_BASE_DATOS_PRUEBAS (ver 04-pruebas/conftest.py).
"""

from __future__ import annotations

import datetime as dt
import io
from decimal import Decimal
from typing import Any

import pytest
from conftest import iniciar
from sqlalchemy import func, select

from plasea.modelos import (
    Asignatura,
    Ausencia,
    BloqueHorario,
    Bitacora,
    Corte,
    Curso,
    EstadoEstudiante,
    Estudiante,
    HistorialEstadoEstudiante,
    Inscripcion,
    MatriculaPeriodo,
    NotaCorte,
    PeriodoAcademico,
    ProgramaAcademico,
    RegistroCursoCorte,
    SesionClase,
    TipoEventoBitacora,
    Usuario,
    db,
)

PROFE = "profe1@plasea.edu.co"
OTRO = "profe2@plasea.edu.co"
AUDITOR = "auditor@plasea.edu.co"
ADMIN = "admin@plasea.edu.co"


def _contar(app: Any, modelo: Any, *condiciones: Any) -> int:
    with app.app_context():
        return db.session.scalar(
            select(func.count()).select_from(modelo).where(*condiciones)
        )


@pytest.fixture()
def escenario(app, crear_usuario):
    """Período en su semana 8 con un curso de profe1 y 3 estudiantes inscritos."""
    from plasea.servicios import calendario, periodos
    from plasea.servicios.comunes import ahora

    profe = crear_usuario(PROFE, rol="profesor", nombre="Profesor Uno")
    otro = crear_usuario(OTRO, rol="profesor", nombre="Profesor Dos")
    auditor = crear_usuario(AUDITOR, rol="auditor_academico", nombre="Auditora")
    hoy = ahora().date()
    lunes = hoy - dt.timedelta(days=hoy.weekday() + 7 * 7)
    with app.app_context():
        programa = db.session.scalar(select(ProgramaAcademico.id))
        activo = db.session.scalar(
            select(EstadoEstudiante.id).where(EstadoEstudiante.codigo == "activo")
        )
        periodo = PeriodoAcademico(
            identificador=f"{hoy.year}-2",
            fecha_inicio=lunes,
            fecha_fin=lunes + dt.timedelta(days=111),
            en_curso_marca=1,
        )
        db.session.add(periodo)
        db.session.flush()
        for datos in periodos.cortes_sugeridos(periodo):
            db.session.add(Corte(periodo_academico_id=periodo.id, **datos.__dict__))
        asignatura = Asignatura(
            codigo="ISI501",
            nombre="Ingeniería de Software I",
            programa_academico_id=programa,
            creditos=4,
            horas_semanales=4,
            nivel=5,
        )
        db.session.add(asignatura)
        db.session.flush()
        cursos = {}
        for codigo, profesor in (("T01", profe), ("T02", otro)):
            curso = Curso(
                asignatura_id=asignatura.id,
                periodo_academico_id=periodo.id,
                codigo=codigo,
                profesor_usuario_id=profesor,
            )
            db.session.add(curso)
            db.session.flush()
            for dia in (1, 3):
                db.session.add(
                    BloqueHorario(
                        curso_id=curso.id,
                        dia_semana=dia,
                        hora_inicio=dt.time(7),
                        hora_fin=dt.time(9),
                    )
                )
            db.session.flush()
            db.session.refresh(curso)
            calendario.regenerar_calendario(curso)
            cursos[codigo] = curso.id
        matriculas = []
        for numero, nombre in enumerate(
            ("Ana Rojas", "Bruno Celis", "Carla Duarte"), start=1
        ):
            estudiante = Estudiante(
                codigo=f"2024100{numero}",
                nombres=nombre,
                correo=f"privado{numero}@correo.co",
                programa_academico_id=programa,
                periodo_ingreso="2024-1",
            )
            db.session.add(estudiante)
            db.session.flush()
            db.session.add(
                HistorialEstadoEstudiante(
                    estudiante_id=estudiante.id,
                    estado_estudiante_id=activo,
                    fecha_efectiva=dt.date(2024, 2, 1),
                    registrado_por_usuario_id=auditor,
                )
            )
            matricula = MatriculaPeriodo(
                estudiante_id=estudiante.id,
                periodo_academico_id=periodo.id,
                semestre_cursado=5,
            )
            db.session.add(matricula)
            db.session.flush()
            matriculas.append(matricula.id)
        inscripciones = []
        for matricula_id in matriculas:
            inscripcion = Inscripcion(
                matricula_periodo_id=matricula_id,
                curso_id=cursos["T01"],
                periodo_academico_id=periodo.id,
            )
            db.session.add(inscripcion)
            db.session.flush()
            inscripciones.append(inscripcion.id)
        db.session.commit()
        cortes = {
            c.numero: c.id
            for c in db.session.scalars(
                select(Corte).where(Corte.periodo_academico_id == periodo.id)
            )
        }
        sesiones = list(
            db.session.execute(
                select(SesionClase.id, SesionClase.fecha)
                .where(SesionClase.curso_id == cursos["T01"])
                .order_by(SesionClase.fecha)
            )
        )
    corte2_inicio = lunes + dt.timedelta(weeks=5)
    return {
        "hoy": hoy,
        "curso": cursos["T01"],
        "curso_otro": cursos["T02"],
        "cortes": cortes,
        "inscripciones": inscripciones,
        "sesion_corte1": next(s for s, f in sesiones if f < corte2_inicio),
        "sesion_corte2": [s for s, f in sesiones if corte2_inicio <= f <= hoy][-1],
        "sesion_futura": next(s for s, f in sesiones if f > hoy),
        "profe": profe,
        "auditor": auditor,
    }


# --- Permisos -------------------------------------------------------------------
def test_solo_el_profesor_accede_al_registro(cliente, escenario):
    iniciar(cliente, AUDITOR)
    assert cliente.get("/registro/").status_code == 403


def test_profesor_no_abre_ni_modifica_cursos_ajenos(app, cliente, escenario):
    iniciar(cliente, PROFE)
    ajeno = escenario["curso_otro"]
    assert cliente.get(f"/registro/cursos/{ajeno}").status_code == 403
    assert cliente.get(f"/registro/cursos/{ajeno}/cortes/2/notas").status_code == 403
    assert cliente.get("/registro/cursos/999999").status_code == 404


# --- RF-26 ----------------------------------------------------------------------
def test_rf26_mis_cursos_con_estado_de_cada_corte(app, cliente, escenario):
    iniciar(cliente, PROFE)
    pagina = cliente.get("/registro/").get_data(as_text=True)
    assert "Ingeniería de Software I" in pagina and "T01" in pagina
    assert "T02" not in pagina  # solo los cursos del profesor autenticado
    assert "Cerrado" in pagina and "Pendiente" in pagina
    assert "Lunes 07:00" in pagina
    with app.app_context():
        db.session.add(
            RegistroCursoCorte(
                curso_id=escenario["curso"],
                corte_id=escenario["cortes"][2],
                estado="enviado",
                enviado_en=dt.datetime.now(),
                enviado_por_usuario_id=escenario["profe"],
            )
        )
        db.session.commit()
    assert "Enviado" in cliente.get("/registro/").get_data(as_text=True)


def test_rf26_menu_del_profesor(cliente, escenario):
    iniciar(cliente, PROFE)
    assert "Mis cursos" in cliente.get("/inicio").get_data(as_text=True)


# --- RF-27 ----------------------------------------------------------------------
def test_rf27_lista_con_codigo_y_nombre_sin_datos_personales(cliente, escenario):
    iniciar(cliente, PROFE)
    pagina = cliente.get(f"/registro/cursos/{escenario['curso']}").get_data(
        as_text=True
    )
    assert "20241001" in pagina and "Ana Rojas" in pagina
    assert "privado1@correo.co" not in pagina


# --- RF-28 ----------------------------------------------------------------------
def _asistencia(cliente, escenario, sesion, ausentes):
    return cliente.post(
        f"/registro/cursos/{escenario['curso']}/sesiones/{sesion}/asistencia",
        data={"ausentes": [str(a) for a in ausentes]},
        follow_redirects=True,
    )


def test_rf28_marcar_ausentes_carga_las_horas_de_la_sesion(app, cliente, escenario):
    iniciar(cliente, PROFE)
    sesion = escenario["sesion_corte2"]
    ausente = escenario["inscripciones"][0]
    respuesta = _asistencia(cliente, escenario, sesion, [ausente]).get_data(
        as_text=True
    )
    assert "1 ausente(s), 2 h a cada uno" in respuesta
    assert _contar(app, Ausencia, Ausencia.ausente.is_(True)) == 1
    with app.app_context():
        registrada = db.session.get(SesionClase, sesion)
        assert registrada.asistencia_registrada_en is not None
        assert registrada.duracion_horas == 2
    assert (
        _contar(app, RegistroCursoCorte, RegistroCursoCorte.estado == "pendiente") == 1
    )


def test_rf28_desmarcar_conserva_la_fila(app, cliente, escenario):
    iniciar(cliente, PROFE)
    sesion = escenario["sesion_corte2"]
    _asistencia(cliente, escenario, sesion, [escenario["inscripciones"][0]])
    respuesta = _asistencia(cliente, escenario, sesion, []).get_data(as_text=True)
    assert "todos presentes" in respuesta
    assert _contar(app, Ausencia) == 1
    assert _contar(app, Ausencia, Ausencia.ausente.is_(True)) == 0


def test_rf28_sesion_futura_o_de_corte_cerrado_no_se_registra(app, cliente, escenario):
    iniciar(cliente, PROFE)
    futura = _asistencia(
        cliente, escenario, escenario["sesion_futura"], [escenario["inscripciones"][0]]
    ).get_data(as_text=True)
    assert "aún no se ha dictado" in futura
    cerrada = _asistencia(
        cliente, escenario, escenario["sesion_corte1"], [escenario["inscripciones"][0]]
    ).get_data(as_text=True)
    assert "está cerrado" in cerrada
    assert _contar(app, Ausencia) == 0


def test_rf28_no_acepta_estudiantes_de_otro_curso(app, cliente, escenario):
    iniciar(cliente, PROFE)
    respuesta = _asistencia(cliente, escenario, escenario["sesion_corte2"], [999999])
    assert "no pertenecen al curso" in respuesta.get_data(as_text=True)
    assert _contar(app, Ausencia) == 0


def test_rf28_tras_el_envio_se_corrige_con_rf31(app, cliente, escenario):
    with app.app_context():
        db.session.add(
            RegistroCursoCorte(
                curso_id=escenario["curso"],
                corte_id=escenario["cortes"][2],
                estado="enviado",
                enviado_en=dt.datetime.now(),
                enviado_por_usuario_id=escenario["profe"],
            )
        )
        db.session.commit()
    iniciar(cliente, PROFE)
    respuesta = _asistencia(
        cliente, escenario, escenario["sesion_corte2"], [escenario["inscripciones"][0]]
    )
    assert "ya se envió" in respuesta.get_data(as_text=True)
    assert _contar(app, Ausencia) == 0


# --- RF-29 ----------------------------------------------------------------------
def _notas(cliente, escenario, numero, valores):
    datos = {
        f"nota-{iid}": valor for iid, valor in zip(escenario["inscripciones"], valores)
    }
    return cliente.post(
        f"/registro/cursos/{escenario['curso']}/cortes/{numero}/notas",
        data=datos,
        follow_redirects=True,
    )


def test_rf29_guardar_borrador_con_coma_decimal(app, cliente, escenario):
    iniciar(cliente, PROFE)
    respuesta = _notas(cliente, escenario, 2, ["3,5", "4", ""]).get_data(as_text=True)
    assert "2 nota(s). Faltan 1." in respuesta
    with app.app_context():
        notas = db.session.scalars(
            select(NotaCorte.nota).order_by(NotaCorte.nota)
        ).all()
    assert notas == [Decimal("3.5"), Decimal("4.0")]
    assert 'value="3,5"' in cliente.get(
        f"/registro/cursos/{escenario['curso']}/cortes/2/notas"
    ).get_data(as_text=True)


def test_rf29_valores_invalidos_no_guardan_nada(app, cliente, escenario):
    iniciar(cliente, PROFE)
    respuesta = _notas(cliente, escenario, 2, ["5,5", "3,45", "4,0"]).get_data(
        as_text=True
    )
    assert "entre 1,0 y 5,0" in respuesta and "un solo decimal" in respuesta
    assert _contar(app, NotaCorte) == 0


def test_rf29_una_nota_guardada_no_se_borra(app, cliente, escenario):
    iniciar(cliente, PROFE)
    _notas(cliente, escenario, 2, ["3,5", "", ""])
    respuesta = _notas(cliente, escenario, 2, ["", "", ""]).get_data(as_text=True)
    assert "no se puede borrar" in respuesta
    _notas(cliente, escenario, 2, ["2,8", "", ""])
    with app.app_context():
        assert db.session.scalar(select(NotaCorte.nota)) == Decimal("2.8")


def test_rf29_fuera_del_plazo_de_carga(app, cliente, escenario):
    iniciar(cliente, PROFE)
    cerrado = _notas(cliente, escenario, 1, ["3,5", "3,5", "3,5"]).get_data(
        as_text=True
    )
    assert "está cerrado" in cerrado
    futuro = _notas(cliente, escenario, 3, ["3,5", "3,5", "3,5"]).get_data(as_text=True)
    assert "inicia el" in futuro
    assert _contar(app, NotaCorte) == 0


# --- RF-24 ----------------------------------------------------------------------
ENCABEZADO = (
    "codigo;nombres;correo;periodo_ingreso;periodo;asignatura;curso;semestre_cursado"
)


def _csv(*filas: str) -> bytes:
    return ("﻿" + "\r\n".join((ENCABEZADO, *filas)) + "\r\n").encode("utf-8")


def _subir(cliente, contenido: bytes, nombre="estudiantes.csv"):
    return cliente.post(
        "/estudiantes/importar",
        data={"archivo": (io.BytesIO(contenido), nombre)},
        content_type="multipart/form-data",
    )


def test_rf24_plantilla_descargable(cliente, escenario):
    iniciar(cliente, AUDITOR)
    respuesta = cliente.get("/estudiantes/importar/plantilla.csv")
    assert respuesta.status_code == 200
    assert respuesta.data.startswith("﻿".encode("utf-8"))
    assert ENCABEZADO in respuesta.data.decode("utf-8-sig")


def test_rf24_validacion_previa_y_confirmacion(app, cliente, escenario):
    iniciar(cliente, AUDITOR)
    periodo = f"{escenario['hoy'].year}-2"
    contenido = _csv(
        f"20262001;Nuevo Estudiante Uno;n1@est.co;2026-2;{periodo};isi501;t01;1",
        "20241001;Ana María Rojas;privado1@correo.co;2024-1;;;;",
        "20262002;Sin Correo Valido;correo-malo;2026-2;;;;",
        f"20262003;Curso Inexistente;n3@estudiantes.co;2026-2;{periodo};ISI999;T01;1",
        "20262004;=HIPERVINCULO(1);n4@estudiantes.co;2026-2;;;;",
        f"20241002;Bruno Celis;privado2@correo.co;2024-1;{periodo};ISI501;T01;5",
    )
    previa = _subir(cliente, contenido).get_data(as_text=True)
    assert "Resumen de estudiantes.csv" in previa
    for texto in ("correo electrónico válido", "No existe el curso ISI999", "fórmulas"):
        assert texto in previa
    assert "Ya está inscrito" in previa
    # No se guarda nada hasta confirmar.
    assert _contar(app, Estudiante) == 3
    assert _contar(app, Inscripcion) == 3

    cliente.post("/estudiantes/importar/confirmar", follow_redirects=True)
    assert _contar(app, Estudiante) == 4
    assert _contar(app, Inscripcion) == 4
    with app.app_context():
        nuevo = db.session.scalar(
            select(Estudiante).where(Estudiante.codigo == "20262001")
        )
        assert nuevo.historial_estados[0].estado_estudiante.codigo == "activo"
        assert (
            db.session.scalar(
                select(Estudiante.nombres).where(Estudiante.codigo == "20241001")
            )
            == "Ana María Rojas"
        )
        evento = db.session.scalar(
            select(Bitacora.detalle)
            .join(TipoEventoBitacora)
            .where(TipoEventoBitacora.codigo == "importacion")
        )
    assert "1 nuevos, 1 actualizados, 1 inscripciones, 4 filas con error" in evento


def test_rf24_cancelar_no_guarda(app, cliente, escenario):
    iniciar(cliente, AUDITOR)
    _subir(cliente, _csv("20262001;Nuevo Estudiante;n1@estudiantes.co;2026-2;;;;"))
    cliente.post("/estudiantes/importar/cancelar")
    respuesta = cliente.post("/estudiantes/importar/confirmar", follow_redirects=True)
    assert "No hay una carga pendiente" in respuesta.get_data(as_text=True)
    assert _contar(app, Estudiante) == 3


def test_rf24_archivo_mayor_a_5_mb(cliente, escenario):
    iniciar(cliente, AUDITOR)
    grande = _csv("x" * (5 * 1024 * 1024))
    respuesta = _subir(cliente, grande)
    assert respuesta.status_code == 302
    pagina = cliente.get(respuesta.headers["Location"]).get_data(as_text=True)
    assert "5 MB" in pagina


def test_rf24_solo_auditor(cliente, escenario):
    iniciar(cliente, PROFE)
    assert cliente.get("/estudiantes/importar").status_code == 403


# --- RF-25 ----------------------------------------------------------------------
@pytest.fixture()
def administrador(app, crear_usuario):
    return crear_usuario(ADMIN, rol="administrador_sistema", nombre="Administrador")


def test_rf25_genera_cuatro_semestres_coherentes(app, administrador):
    from plasea.servicios import datos_prueba
    from plasea.servicios.comunes import ErrorNegocio

    volumen = datos_prueba.Volumen(
        estudiantes_iniciales=60, nuevos_por_periodo=12, historicos=15
    )
    with app.app_context():
        resumen = datos_prueba.generar(ADMIN, semilla=7, volumen=volumen)
    assert resumen["Períodos"] == 4 and resumen["Cortes"] == 12
    assert resumen["Asignaturas"] == 25 and resumen["Cursos"] == 200
    assert _contar(app, PeriodoAcademico, PeriodoAcademico.en_curso_marca == 1) == 1
    assert _contar(app, Usuario, Usuario.correo == PROFE) == 1
    with app.app_context():
        # Cada inscripción está en un curso del mismo período que su matrícula.
        incoherentes = db.session.scalar(
            select(func.count(Inscripcion.id))
            .join(
                MatriculaPeriodo,
                MatriculaPeriodo.id == Inscripcion.matricula_periodo_id,
            )
            .join(Curso, Curso.id == Inscripcion.curso_id)
            .where(
                (MatriculaPeriodo.periodo_academico_id != Curso.periodo_academico_id)
            )
        )
        assert incoherentes == 0
        minimo, maximo = db.session.execute(
            select(func.min(NotaCorte.nota), func.max(NotaCorte.nota))
        ).one()
        assert Decimal("1.0") <= minimo <= maximo <= Decimal("5.0")
        # Las ausencias solo se registran en sesiones ya registradas.
        sin_registro = db.session.scalar(
            select(func.count(Ausencia.id))
            .join(SesionClase, SesionClase.id == Ausencia.sesion_clase_id)
            .where(SesionClase.asistencia_registrada_en.is_(None))
        )
        assert sin_registro == 0
        assert (
            db.session.scalar(select(func.max(MatriculaPeriodo.semestre_cursado))) <= 10
        )
        with pytest.raises(ErrorNegocio, match="--reiniciar"):
            datos_prueba.generar(ADMIN, volumen=volumen)
    total = _contar(app, Estudiante)
    with app.app_context():
        datos_prueba.generar(ADMIN, reiniciar=True, semilla=7, volumen=volumen)
    assert _contar(app, Estudiante) == total  # repetible con la misma semilla


def test_rf25_solo_un_administrador_activo_ejecuta(app, crear_usuario):
    from plasea.servicios import datos_prueba
    from plasea.servicios.comunes import ErrorNegocio

    crear_usuario(AUDITOR, rol="auditor_academico")
    with app.app_context(), pytest.raises(ErrorNegocio, match="Administrador"):
        datos_prueba.generar(AUDITOR)


def test_rf25_comando_flask(app, administrador, monkeypatch):
    from plasea.servicios import datos_prueba

    original = datos_prueba.generar
    monkeypatch.setattr(
        datos_prueba,
        "generar",
        lambda **opciones: original(volumen=datos_prueba.Volumen(20, 5, 5), **opciones),
    )
    resultado = app.test_cli_runner().invoke(args=["generar-datos-prueba"])
    assert resultado.exit_code == 0, resultado.output
    assert "Datos de prueba generados." in resultado.output
    assert _contar(app, PeriodoAcademico) == 4
