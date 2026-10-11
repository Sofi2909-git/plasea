"""Pruebas funcionales del módulo 3.3: estructura académica (RF-13 a RF-20),
estudiantes e inscripciones (RF-21 a RF-23) y ayuda (RF-62, RF-63).

Derivadas de los criterios de aceptación de REQUERIMIENTOS.txt. Requieren
URL_BASE_DATOS_PRUEBAS (ver 04-pruebas/conftest.py).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest
from conftest import iniciar
from sqlalchemy import func, select

from plasea.modelos import (
    Asignatura,
    BloqueHorario,
    Bitacora,
    ConfiguracionAlerta,
    Corte,
    Curso,
    Estudiante,
    Festivo,
    HistorialEstadoEstudiante,
    Inscripcion,
    MatriculaPeriodo,
    PeriodoAcademico,
    ProgramaAcademico,
    SesionClase,
    db,
)

AUDITOR = "auditor@plasea.edu.co"
PROFE = "profe1@plasea.edu.co"
LUNES = dt.date(2026, 8, 3)
FIN = LUNES + dt.timedelta(days=111)


@pytest.fixture()
def auditor(cliente, crear_usuario):
    """Cliente con sesión de Auditor académico y un profesor disponible."""
    crear_usuario(AUDITOR, rol="auditor_academico", nombre="Auditora Prueba")
    crear_usuario(PROFE, rol="profesor", nombre="Profesor Uno")
    iniciar(cliente, AUDITOR)
    return cliente


def _programa_id(app: Any) -> int:
    with app.app_context():
        return db.session.scalar(select(ProgramaAcademico.id))


def _contar(app: Any, modelo: Any, *condiciones: Any) -> int:
    with app.app_context():
        return db.session.scalar(
            select(func.count()).select_from(modelo).where(*condiciones)
        )


def _crear_periodo(cliente: Any, identificador: str = "2026-2", inicio=LUNES, fin=FIN):
    return cliente.post(
        "/estructura/periodos/nuevo",
        data={
            "identificador": identificador,
            "fecha_inicio": inicio.isoformat(),
            "fecha_fin": fin.isoformat(),
        },
    )


def _id(app: Any, modelo: Any, *condiciones: Any) -> int:
    with app.app_context():
        return db.session.scalar(select(modelo.id).where(*condiciones))


def _crear_asignatura(app, cliente, codigo="ISI501", horas=4):
    cliente.post(
        "/estructura/asignaturas/nueva",
        data={
            "codigo": codigo,
            "nombre": "Ingeniería de Software I",
            "programa_academico_id": _programa_id(app),
            "creditos": 4,
            "horas_semanales": horas,
            "nivel": 5,
        },
    )
    return _id(app, Asignatura, Asignatura.codigo == codigo)


def _crear_curso(app, cliente, codigo="T01"):
    _crear_periodo(cliente)
    asignatura_id = _crear_asignatura(app, cliente)
    periodo_id = _id(app, PeriodoAcademico, PeriodoAcademico.identificador == "2026-2")
    profesor_id = _profesor_id(app)
    cliente.post(
        "/estructura/cursos/nuevo",
        data={
            "periodo_academico_id": periodo_id,
            "asignatura_id": asignatura_id,
            "codigo": codigo,
            "profesor_usuario_id": profesor_id,
        },
    )
    return _id(app, Curso, Curso.codigo == codigo, Curso.asignatura_id == asignatura_id)


def _profesor_id(app):
    from plasea.modelos import Usuario

    return _id(app, Usuario, Usuario.correo == PROFE)


# --- Permisos ----------------------------------------------------------------
@pytest.mark.parametrize(
    "ruta",
    ["/estructura/", "/estructura/periodos", "/estructura/cursos", "/estudiantes/"],
)
def test_solo_el_auditor_gestiona_estructura_y_estudiantes(
    cliente, crear_usuario, ruta
):
    crear_usuario(PROFE)
    iniciar(cliente, PROFE)
    assert cliente.get(ruta).status_code == 403


def test_menu_del_auditor_muestra_estructura_y_estudiantes(auditor):
    texto = auditor.get("/inicio").get_data(as_text=True)
    assert "Estructura académica" in texto and "Estudiantes" in texto


# --- RF-13 -------------------------------------------------------------------
def test_rf13_registrar_y_modificar_asignatura(app, auditor):
    asignatura_id = _crear_asignatura(app, auditor, codigo="isi501")
    with app.app_context():
        asignatura = db.session.get(Asignatura, asignatura_id)
        assert asignatura.codigo == "ISI501" and asignatura.creditos == 4
    auditor.post(
        f"/estructura/asignaturas/{asignatura_id}/editar",
        data={
            "codigo": "ISI501",
            "nombre": "Ingeniería de Software",
            "programa_academico_id": _programa_id(app),
            "creditos": 3,
            "horas_semanales": 3,
            "nivel": 6,
        },
    )
    with app.app_context():
        assert db.session.get(Asignatura, asignatura_id).nivel == 6
    assert "Ingeniería de Software" in auditor.get(
        "/estructura/asignaturas?q=software"
    ).get_data(as_text=True)


def test_rf13_codigo_unico_y_creditos_3_o_4(app, auditor):
    _crear_asignatura(app, auditor)
    repetida = auditor.post(
        "/estructura/asignaturas/nueva",
        data={
            "codigo": "ISI501",
            "nombre": "Otra",
            "programa_academico_id": _programa_id(app),
            "creditos": 3,
            "horas_semanales": 3,
            "nivel": 1,
        },
    )
    assert "Ya existe una asignatura" in repetida.get_data(as_text=True)
    creditos = auditor.post(
        "/estructura/asignaturas/nueva",
        data={
            "codigo": "ISI999",
            "nombre": "Créditos inválidos",
            "programa_academico_id": _programa_id(app),
            "creditos": 5,
            "horas_semanales": 3,
            "nivel": 1,
        },
    )
    assert creditos.status_code == 200
    assert _contar(app, Asignatura) == 1


def test_rf13_no_se_elimina_una_asignatura_con_cursos(app, auditor):
    curso_id = _crear_curso(app, auditor)
    with app.app_context():
        asignatura_id = db.session.get(Curso, curso_id).asignatura_id
    respuesta = auditor.post(
        f"/estructura/asignaturas/{asignatura_id}/eliminar", follow_redirects=True
    )
    assert "no se puede eliminar" in respuesta.get_data(as_text=True)
    assert _contar(app, Asignatura) == 1
    sin_cursos = _crear_asignatura(app, auditor, codigo="ISI777")
    auditor.post(f"/estructura/asignaturas/{sin_cursos}/eliminar")
    assert _contar(app, Asignatura) == 1


# --- RF-16 -------------------------------------------------------------------
def test_rf16_registrar_periodo_de_16_semanas(app, auditor):
    respuesta = _crear_periodo(auditor)
    assert respuesta.status_code == 302
    assert _contar(app, PeriodoAcademico) == 1
    largo = _crear_periodo(auditor, "2027-1", dt.date(2027, 2, 1), dt.date(2027, 7, 1))
    assert "16 semanas" in largo.get_data(as_text=True)
    assert _contar(app, PeriodoAcademico) == 1


def test_rf16_solo_un_periodo_en_curso(app, auditor):
    _crear_periodo(auditor, "2026-1", dt.date(2026, 2, 2), dt.date(2026, 5, 24))
    _crear_periodo(auditor)
    primero = _id(app, PeriodoAcademico, PeriodoAcademico.identificador == "2026-1")
    segundo = _id(app, PeriodoAcademico, PeriodoAcademico.identificador == "2026-2")
    auditor.post(f"/estructura/periodos/{primero}/en-curso")
    auditor.post(f"/estructura/periodos/{segundo}/en-curso")
    assert _contar(app, PeriodoAcademico, PeriodoAcademico.en_curso_marca == 1) == 1
    with app.app_context():
        assert db.session.get(PeriodoAcademico, segundo).en_curso_marca == 1
    # Los períodos anteriores se conservan para consulta.
    assert _contar(app, PeriodoAcademico) == 2


# --- RF-17 -------------------------------------------------------------------
def _datos_cortes(pesos=("30", "30", "40")):
    datos = {}
    tramos = [
        (LUNES, LUNES + dt.timedelta(days=34)),
        (LUNES + dt.timedelta(days=35), LUNES + dt.timedelta(days=69)),
        (LUNES + dt.timedelta(days=70), FIN),
    ]
    for indice, (peso, (inicio, fin)) in enumerate(zip(pesos, tramos)):
        prefijo = f"cortes-{indice}-"
        datos.update(
            {
                prefijo + "peso_porcentaje": peso,
                prefijo + "fecha_inicio": inicio.isoformat(),
                prefijo + "fecha_fin": fin.isoformat(),
                prefijo + "limite_carga": (fin + dt.timedelta(days=3)).isoformat(),
                prefijo + "limite_correccion": (fin + dt.timedelta(days=7)).isoformat(),
            }
        )
    return datos


def test_rf17_definir_cortes_con_pesos_que_suman_100(app, auditor):
    _crear_periodo(auditor)
    periodo_id = _id(app, PeriodoAcademico)
    sugeridos = auditor.get(f"/estructura/periodos/{periodo_id}/cortes").get_data(
        as_text=True
    )
    assert 'value="30"' in sugeridos and 'value="40"' in sugeridos
    malos = auditor.post(
        f"/estructura/periodos/{periodo_id}/cortes",
        data=_datos_cortes(("30", "30", "30")),
    )
    assert "deben sumar 100" in malos.get_data(as_text=True)
    assert _contar(app, Corte) == 0
    buenos = auditor.post(
        f"/estructura/periodos/{periodo_id}/cortes",
        data=_datos_cortes(("30", "30,5", "39,5")),
    )
    assert buenos.status_code == 302
    with app.app_context():
        pesos = db.session.scalars(
            select(Corte.peso_porcentaje).order_by(Corte.numero)
        ).all()
    assert pesos == [Decimal("30.00"), Decimal("30.50"), Decimal("39.50")]


def test_rf17_corte_cerrado_no_se_modifica(app, auditor):
    _crear_periodo(auditor)
    periodo_id = _id(app, PeriodoAcademico)
    auditor.post(f"/estructura/periodos/{periodo_id}/cortes", data=_datos_cortes())
    with app.app_context():
        corte = db.session.scalar(select(Corte).where(Corte.numero == 1))
        corte.cerrado_en = dt.datetime(2026, 9, 14, 0, 0)
        corte.tipo_cierre = "automatico"
        db.session.commit()
    datos = _datos_cortes(("35", "25", "40"))
    respuesta = auditor.post(f"/estructura/periodos/{periodo_id}/cortes", data=datos)
    assert "está cerrado" in respuesta.get_data(as_text=True)


# --- RF-14, RF-15 y RF-19 -----------------------------------------------------
def test_rf14_curso_con_codigo_unico_por_asignatura_y_periodo(app, auditor):
    curso_id = _crear_curso(app, auditor)
    assert curso_id is not None
    with app.app_context():
        curso = db.session.get(Curso, curso_id)
        datos = {
            "periodo_academico_id": curso.periodo_academico_id,
            "asignatura_id": curso.asignatura_id,
            "codigo": "t01",
            "profesor_usuario_id": curso.profesor_usuario_id,
        }
    repetido = auditor.post("/estructura/cursos/nuevo", data=datos)
    assert "Ya existe el curso T01" in repetido.get_data(as_text=True)
    datos["codigo"] = "T02"
    auditor.post("/estructura/cursos/nuevo", data=datos)
    # Un docente puede tener varios cursos.
    assert (
        _contar(app, Curso, Curso.profesor_usuario_id == datos["profesor_usuario_id"])
        == 2
    )


def test_rf14_el_docente_debe_tener_rol_profesor(app, auditor):
    _crear_curso(app, auditor)
    with app.app_context():
        curso = db.session.scalar(select(Curso))
        from plasea.modelos import Usuario

        auditor_id = db.session.scalar(
            select(Usuario.id).where(Usuario.correo == AUDITOR)
        )
        datos = {"codigo": "T01", "profesor_usuario_id": auditor_id}
    respuesta = auditor.post(f"/estructura/cursos/{curso.id}/editar", data=datos)
    assert "rol Profesor" in respuesta.get_data(as_text=True)


def test_rf15_rf19_horario_y_calendario_de_64_horas(app, auditor):
    curso_id = _crear_curso(app, auditor)
    for dia in (1, 3):
        auditor.post(
            f"/estructura/cursos/{curso_id}/bloques",
            data={"dia_semana": dia, "hora_inicio": "07:00", "hora_fin": "09:00"},
        )
    assert _contar(app, BloqueHorario) == 2
    with app.app_context():
        horas = db.session.scalar(
            select(func.sum(SesionClase.duracion_horas)).where(
                SesionClase.curso_id == curso_id
            )
        )
    assert horas == 64
    detalle = auditor.get(f"/estructura/cursos/{curso_id}").get_data(as_text=True)
    assert "64" in detalle and "32" in detalle


def test_rf15_solapamiento_duracion_y_advertencia_de_horas(app, auditor):
    curso_id = _crear_curso(app, auditor)
    primero = auditor.post(
        f"/estructura/cursos/{curso_id}/bloques",
        data={"dia_semana": 1, "hora_inicio": "07:00", "hora_fin": "09:00"},
        follow_redirects=True,
    ).get_data(as_text=True)
    assert "suma 2 h por semana" in primero  # la asignatura tiene 4 h
    solapado = auditor.post(
        f"/estructura/cursos/{curso_id}/bloques",
        data={"dia_semana": 1, "hora_inicio": "08:00", "hora_fin": "10:00"},
        follow_redirects=True,
    ).get_data(as_text=True)
    assert "se solapa" in solapado
    largo = auditor.post(
        f"/estructura/cursos/{curso_id}/bloques",
        data={"dia_semana": 2, "hora_inicio": "07:00", "hora_fin": "11:00"},
        follow_redirects=True,
    ).get_data(as_text=True)
    assert "1, 2 o 3 horas" in largo
    assert _contar(app, BloqueHorario) == 1


def test_rf19_no_se_regenera_con_asistencia_registrada(app, auditor):
    curso_id = _crear_curso(app, auditor)
    auditor.post(
        f"/estructura/cursos/{curso_id}/bloques",
        data={"dia_semana": 1, "hora_inicio": "07:00", "hora_fin": "09:00"},
    )
    with app.app_context():
        from plasea.modelos import Usuario

        profesor_id = db.session.scalar(
            select(Usuario.id).where(Usuario.correo == PROFE)
        )
        sesion = db.session.scalar(select(SesionClase).order_by(SesionClase.fecha))
        sesion.asistencia_registrada_por_usuario_id = profesor_id
        sesion.asistencia_registrada_en = dt.datetime(2026, 8, 3, 9, 0)
        db.session.commit()
    respuesta = auditor.post(
        f"/estructura/cursos/{curso_id}/bloques",
        data={"dia_semana": 3, "hora_inicio": "07:00", "hora_fin": "09:00"},
        follow_redirects=True,
    ).get_data(as_text=True)
    assert "asistencia registrada" in respuesta
    assert _contar(app, SesionClase, SesionClase.curso_id == curso_id) == 16


# --- RF-18 -------------------------------------------------------------------
def test_rf18_festivo_unico_dentro_del_periodo_y_regenera_calendario(app, auditor):
    curso_id = _crear_curso(app, auditor)
    auditor.post(
        f"/estructura/cursos/{curso_id}/bloques",
        data={"dia_semana": 1, "hora_inicio": "07:00", "hora_fin": "09:00"},
    )
    periodo_id = _id(app, PeriodoAcademico)
    festivo = LUNES + dt.timedelta(weeks=2)
    respuesta = auditor.post(
        f"/estructura/periodos/{periodo_id}/festivos",
        data={"fecha": festivo.isoformat()},
        follow_redirects=True,
    ).get_data(as_text=True)
    assert "Se regeneró el calendario de 1 curso" in respuesta
    assert _contar(app, SesionClase, SesionClase.curso_id == curso_id) == 15
    repetido = auditor.post(
        f"/estructura/periodos/{periodo_id}/festivos",
        data={"fecha": festivo.isoformat()},
        follow_redirects=True,
    ).get_data(as_text=True)
    assert "ya está registrado" in repetido
    fuera = auditor.post(
        f"/estructura/periodos/{periodo_id}/festivos",
        data={"fecha": (FIN + dt.timedelta(days=5)).isoformat()},
        follow_redirects=True,
    ).get_data(as_text=True)
    assert "dentro de las fechas" in fuera
    assert _contar(app, Festivo) == 1
    festivo_id = _id(app, Festivo)
    auditor.post(f"/estructura/festivos/{festivo_id}/eliminar")
    assert _contar(app, SesionClase, SesionClase.curso_id == curso_id) == 16


# --- RF-20 -------------------------------------------------------------------
def test_rf20_cambiar_umbrales_conserva_historial(app, auditor):
    pagina = auditor.get("/estructura/umbrales").get_data(as_text=True)
    assert 'value="3"' in pagina or 'value="3,0"' in pagina
    respuesta = auditor.post(
        "/estructura/umbrales",
        data={
            "nota_aprobacion": "3,0",
            "limite_perdida_inasistencia": "25",
            "umbral_amarillo_inasistencia": "15",
            "nota_amarilla_minima": "3,0",
            "nota_amarilla_maxima": "3,5",
        },
    )
    assert respuesta.status_code == 302
    assert _contar(app, ConfiguracionAlerta) == 2
    from plasea.servicios.umbrales import configuracion_vigente

    with app.app_context():
        vigente = configuracion_vigente()
        assert vigente.limite_perdida_inasistencia == Decimal("25.00")
        assert vigente.nota_amarilla_maxima == Decimal("3.5")


def test_rf20_valores_invalidos_no_crean_version(app, auditor):
    auditor.post(
        "/estructura/umbrales",
        data={
            "nota_aprobacion": "3,0",
            "limite_perdida_inasistencia": "20",
            "umbral_amarillo_inasistencia": "25",
            "nota_amarilla_minima": "3,0",
            "nota_amarilla_maxima": "3,4",
        },
    )
    assert _contar(app, ConfiguracionAlerta) == 1


# --- RF-21 y RF-22 -----------------------------------------------------------
def _crear_estudiante(
    app, cliente, codigo="20231001", activo_desde=dt.date(2024, 2, 1)
):
    return cliente.post(
        "/estudiantes/nuevo",
        data={
            "codigo": codigo,
            "nombres": "Laura Camila Rojas Peña",
            "correo": f"{codigo}@estudiantes.plasea.edu.co",
            "programa_academico_id": _programa_id(app),
            "periodo_ingreso": "2024-1",
            "fecha_estado_inicial": activo_desde.isoformat(),
        },
    )


def test_rf21_registrar_estudiante_con_codigo_unico(app, auditor):
    assert _crear_estudiante(app, auditor).status_code == 302
    repetido = _crear_estudiante(app, auditor)
    assert "Ya existe un estudiante" in repetido.get_data(as_text=True)
    assert _contar(app, Estudiante) == 1
    assert _contar(app, HistorialEstadoEstudiante) == 1
    lista = auditor.get("/estudiantes/?q=ROJAS&cohorte=2024-1&estado=activo").get_data(
        as_text=True
    )
    assert "Laura Camila Rojas Peña" in lista


def test_rf22_historial_de_estados_consultable(app, auditor):
    _crear_estudiante(app, auditor)
    estudiante_id = _id(app, Estudiante)
    auditor.post(
        f"/estudiantes/{estudiante_id}/estados",
        data={"estado": "aplazo_semestre", "fecha_efectiva": "2025-08-01"},
    )
    auditor.post(
        f"/estudiantes/{estudiante_id}/estados",
        data={"estado": "activo", "fecha_efectiva": "2026-02-01"},
    )
    assert _contar(app, HistorialEstadoEstudiante) == 3
    ficha = auditor.get(f"/estudiantes/{estudiante_id}").get_data(as_text=True)
    assert "Aplazó semestre" in ficha and "01/02/2026" in ficha


# --- RF-23 -------------------------------------------------------------------
def test_rf23_inscribir_retirar_y_no_repetir(app, auditor):
    curso_id = _crear_curso(app, auditor)
    _crear_estudiante(app, auditor)
    auditor.post(
        f"/estudiantes/cursos/{curso_id}/inscripciones",
        data={"codigo_estudiante": "20231001", "semestre_cursado": 6},
    )
    assert _contar(app, Inscripcion) == 1
    with app.app_context():
        assert db.session.scalar(select(MatriculaPeriodo.semestre_cursado)) == 6
    repetida = auditor.post(
        f"/estudiantes/cursos/{curso_id}/inscripciones",
        data={"codigo_estudiante": "20231001", "semestre_cursado": 6},
        follow_redirects=True,
    ).get_data(as_text=True)
    assert "Ya está inscrito" in repetida
    inscripcion_id = _id(app, Inscripcion)
    auditor.post(f"/estudiantes/inscripciones/{inscripcion_id}/retirar")
    with app.app_context():
        assert db.session.get(Inscripcion, inscripcion_id).retirada_en is not None
    assert _contar(app, Inscripcion) == 1  # el retiro conserva la fila
    otra_vez = auditor.post(
        f"/estudiantes/cursos/{curso_id}/inscripciones",
        data={"codigo_estudiante": "20231001", "semestre_cursado": 6},
        follow_redirects=True,
    ).get_data(as_text=True)
    assert "no se inscribe dos veces" in otra_vez


def test_rf23_solo_se_inscriben_estudiantes_activos(app, auditor):
    curso_id = _crear_curso(app, auditor)
    _crear_estudiante(app, auditor)
    estudiante_id = _id(app, Estudiante)
    auditor.post(
        f"/estudiantes/{estudiante_id}/estados",
        data={"estado": "aplazo_semestre", "fecha_efectiva": "2026-07-01"},
    )
    respuesta = auditor.post(
        f"/estudiantes/cursos/{curso_id}/inscripciones",
        data={"codigo_estudiante": "20231001", "semestre_cursado": 6},
        follow_redirects=True,
    ).get_data(as_text=True)
    assert "Solo se inscriben estudiantes activos" in respuesta
    assert _contar(app, Inscripcion) == 0


def test_rf22_graduado_no_se_inscribe_en_periodos_posteriores(app, auditor):
    curso_id = _crear_curso(app, auditor)
    _crear_estudiante(app, auditor)
    estudiante_id = _id(app, Estudiante)
    auditor.post(
        f"/estudiantes/{estudiante_id}/estados",
        data={"estado": "graduado", "fecha_efectiva": "2026-06-30"},
    )
    respuesta = auditor.post(
        f"/estudiantes/cursos/{curso_id}/inscripciones",
        data={"codigo_estudiante": "20231001", "semestre_cursado": 10},
        follow_redirects=True,
    ).get_data(as_text=True)
    assert "no se puede inscribir en el período 2026-2" in respuesta
    assert _contar(app, Inscripcion) == 0


def test_cambios_de_estructura_quedan_en_bitacora(app, auditor):
    _crear_curso(app, auditor)
    assert (
        _contar(app, Bitacora) >= 3
    )  # período, asignatura y curso (más el inicio de sesión)


# --- RF-62 y RF-63 -----------------------------------------------------------
def test_rf62_acerca_de_desde_el_menu_de_todos_los_roles(cliente, crear_usuario):
    for correo, rol in (
        ("p@plasea.edu.co", "profesor"),
        ("a@plasea.edu.co", "auditor_academico"),
        ("s@plasea.edu.co", "administrador_sistema"),
    ):
        crear_usuario(correo, rol=rol)
        iniciar(cliente, correo)
        inicio = cliente.get("/inicio").get_data(as_text=True)
        assert "/ayuda/acerca" in inicio and "/ayuda/politicas" in inicio
        assert cliente.get("/ayuda/acerca").status_code == 200
        with cliente.session_transaction() as sesion_web:
            sesion_web.clear()


def test_rf62_acerca_de_requiere_sesion(cliente):
    assert cliente.get("/ayuda/acerca").status_code == 302


def test_rf63_politicas_visibles_sin_sesion_y_desde_el_inicio_de_sesion(cliente):
    login = cliente.get("/iniciar-sesion").get_data(as_text=True)
    assert "/ayuda/politicas" in login
    politicas = cliente.get("/ayuda/politicas")
    assert politicas.status_code == 200
    assert "datos ficticios" in politicas.get_data(as_text=True)
