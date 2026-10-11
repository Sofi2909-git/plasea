"""Pruebas funcionales de RF-33, RF-45 a RF-53 y RF-58 a RF-60.

Usan el generador de RF-25 con un volumen reducido (4 semestres con alertas),
así los resultados se comparan contra datos coherentes. Requieren
URL_BASE_DATOS_PRUEBAS.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest
from conftest import iniciar as _iniciar
from sqlalchemy import func, select

from plasea.modelos import (
    Alerta,
    Ausencia,
    Bitacora,
    Corte,
    Curso,
    Estudiante,
    HistorialAusencia,
    HistorialNota,
    Inscripcion,
    MatriculaPeriodo,
    NotaCorte,
    PeriodoAcademico,
    RegistroCausaNoContinuidad,
    TipoEventoBitacora,
    Usuario,
    db,
)

ADMIN, AUDITOR, PROFE = (
    "admin@plasea.edu.co",
    "auditor@plasea.edu.co",
    "profe1@plasea.edu.co",
)


def iniciar(cliente: Any, correo: str) -> Any:
    """Cambia de usuario cerrando la sesión anterior."""
    cliente.post("/cerrar-sesion")
    return _iniciar(cliente, correo)


@pytest.fixture()
def datos(app, crear_usuario):
    """Cuatro semestres generados con RF-25 y un Auditor académico."""
    from plasea.servicios import datos_prueba

    crear_usuario(ADMIN, rol="administrador_sistema")
    crear_usuario(AUDITOR, rol="auditor_academico", nombre="Auditora")
    with app.app_context():
        datos_prueba.generar(ADMIN, semilla=11, volumen=datos_prueba.Volumen(40, 8, 5))
        primero = db.session.scalar(
            select(Corte)
            .join(PeriodoAcademico)
            .where(PeriodoAcademico.identificador == "2025-1", Corte.numero == 3)
        )
    return {"corte_2025_1_c3": primero.id}


def _evento(app: Any, codigo: str) -> int:
    with app.app_context():
        return db.session.scalar(
            select(func.count(Bitacora.id))
            .join(TipoEventoBitacora)
            .where(TipoEventoBitacora.codigo == codigo)
        )


# --- Permisos -------------------------------------------------------------------
@pytest.mark.parametrize(
    "ruta",
    [
        "/alertas/resultados",
        "/alertas/historico",
        "/continuidad/",
        "/registro/historial",
        "/exportacion/alertas.csv",
        "/exportacion/resultados.csv",
    ],
)
def test_solo_el_auditor(cliente, crear_usuario, ruta):
    crear_usuario(PROFE)
    iniciar(cliente, PROFE)
    assert cliente.get(ruta).status_code == 403


# --- RF-45 y RF-46 ----------------------------------------------------------------
def test_rf45_detalle_coincide_con_la_alerta(app, cliente, datos):
    with app.app_context():
        alerta = db.session.scalar(
            select(Alerta)
            .where(Alerta.estado_alerta == "roja", Alerta.nota_requerida.is_not(None))
            .limit(1)
        )
        acumulada = f"{alerta.nota_acumulada:.2f}".replace(".", ",")
        requerida = f"{alerta.nota_requerida:.2f}".replace(".", ",")
        url = f"/alertas/detalle/{alerta.inscripcion_id}?corte={alerta.corte.numero}"
        horas = f"{alerta.horas_ausentes} h"
    iniciar(cliente, AUDITOR)
    pagina = cliente.get(url).get_data(as_text=True)
    assert "Roja" in pagina and acumulada in pagina and requerida in pagina
    assert horas in pagina
    assert (
        "Por nota" in pagina
        or "Nota e inasistencia" in pagina
        or "Por inasistencia" in pagina
    )


def test_rf46_riesgo_alto_dos_o_mas_asignaturas(app, datos):
    from plasea.servicios import analitica

    with app.app_context():
        corte_id = datos["corte_2025_1_c3"]
        esperados: dict[int, set[int]] = {}
        for estudiante_id, asignatura_id in db.session.execute(
            select(MatriculaPeriodo.estudiante_id, Curso.asignatura_id)
            .join(Inscripcion, Inscripcion.matricula_periodo_id == MatriculaPeriodo.id)
            .join(Curso, Curso.id == Inscripcion.curso_id)
            .join(Alerta, Alerta.inscripcion_id == Inscripcion.id)
            .where(Alerta.corte_id == corte_id, Alerta.estado_alerta != "verde")
        ):
            esperados.setdefault(estudiante_id, set()).add(asignatura_id)
        en_riesgo = {e for e, a in esperados.items() if len(a) >= 2}
        assert analitica.estudiantes_en_riesgo(corte_id) == en_riesgo
        assert en_riesgo  # el escenario tiene casos


# --- RF-47 y RF-60 ----------------------------------------------------------------
def _estudiante_con_cuatro_semestres(app) -> Estudiante:
    with app.app_context():
        estudiante_id = db.session.scalar(
            select(MatriculaPeriodo.estudiante_id)
            .group_by(MatriculaPeriodo.estudiante_id)
            .having(func.count(MatriculaPeriodo.id) == 4)
            .limit(1)
        )
        return db.session.get(Estudiante, estudiante_id).id


def test_rf47_historico_de_cuatro_semestres_con_resultado(app, cliente, datos):
    estudiante_id = _estudiante_con_cuatro_semestres(app)
    iniciar(cliente, AUDITOR)
    pagina = cliente.get(f"/alertas/historico/{estudiante_id}").get_data(as_text=True)
    for periodo in ("2025-1", "2025-2", "2026-1", "2026-2"):
        assert periodo in pagina
    assert "Aprobada" in pagina or "Perdida" in pagina
    assert "En curso" in pagina  # 2026-2
    busqueda = cliente.get("/alertas/historico?q=2025").get_data(as_text=True)
    assert "/alertas/historico/" in busqueda


def test_rf47_resultado_coincide_con_el_calculo(app, datos):
    from plasea.servicios import analitica, calculos

    estudiante_id = _estudiante_con_cuatro_semestres(app)
    with app.app_context():
        _e, semestres = analitica.historico_estudiante(estudiante_id)
        terminado = [s for s in semestres if s.periodo.identificador == "2025-1"][0]
        for fila in terminado.filas:
            if fila.resultado == "retirada":
                continue
            esperado = calculos.nota_acumulada(
                zip(fila.notas, [c.peso_porcentaje for c in terminado.cortes])
            )
            assert fila.acumulada == esperado
            if fila.resultado == "aprobada":
                assert fila.acumulada >= Decimal("3.0")
                assert fila.inasistencia <= Decimal("30")
            else:
                assert fila.motivo in ("nota", "inasistencia", "ambos")


def test_rf60_vista_imprimible_sin_menu_con_fecha_y_usuario(app, cliente, datos):
    estudiante_id = _estudiante_con_cuatro_semestres(app)
    iniciar(cliente, AUDITOR)
    pagina = cliente.get(f"/exportacion/historico/{estudiante_id}").get_data(
        as_text=True
    )
    assert "barra-plasea" not in pagina and "menu-principal" not in pagina
    assert "Generado el" in pagina and "por Auditora" in pagina
    assert "Histórico académico" in pagina
    assert _evento(app, "exportacion") == 1


# --- RF-48 y RF-59 ----------------------------------------------------------------
def test_rf48_totales_coinciden_con_la_lista_de_alertas(app, cliente, datos):
    from plasea.servicios import alertas, analitica

    with app.app_context():
        corte = db.session.get(Corte, datos["corte_2025_1_c3"])
        filas, total = analitica.resultados(corte, analitica.FiltrosResultados())
        resumen = alertas.resumen_corte(corte)
        assert total.en_alerta == resumen["roja"] + resumen["amarilla"]
        assert (
            total.inscritos == resumen["roja"] + resumen["amarilla"] + resumen["verde"]
        )
        assert total.aprobados + total.perdidos == total.inscritos  # último corte
        profesor = db.session.scalar(select(Usuario.id).where(Usuario.correo == PROFE))
        propios, _ = analitica.resultados(
            corte, analitica.FiltrosResultados(profesor_id=profesor)
        )
        assert 0 < len(propios) < len(filas)
    iniciar(cliente, AUDITOR)
    pagina = cliente.get(
        "/alertas/resultados?periodo=%d&corte=3" % corte.periodo_academico_id
    )
    assert f"Total ({len(filas)} cursos)" in pagina.get_data(as_text=True)


def test_rf59_csv_de_resultados_respeta_filtros(app, cliente, datos):
    with app.app_context():
        corte = db.session.get(Corte, datos["corte_2025_1_c3"])
        periodo_id = corte.periodo_academico_id
    iniciar(cliente, AUDITOR)
    respuesta = cliente.get(f"/exportacion/resultados.csv?periodo={periodo_id}&corte=3")
    texto = respuesta.data.decode("utf-8-sig")
    lineas = texto.strip().split("\r\n")
    assert lineas[0].startswith("Asignatura;Nombre asignatura;Curso;Profesor;Inscritos")
    from plasea.servicios import analitica

    with app.app_context():
        filas, _total = analitica.resultados(
            db.session.get(Corte, datos["corte_2025_1_c3"]),
            analitica.FiltrosResultados(),
        )
    assert len(lineas) == len(filas) + 2  # cursos, encabezado y total
    filtrado = cliente.get(
        f"/exportacion/resultados.csv?periodo={periodo_id}&corte=3&curso=999999"
    ).data.decode("utf-8-sig")
    assert len(filtrado.strip().split("\r\n")) == 2  # solo encabezado y total
    assert _evento(app, "exportacion") == 2


# --- RF-58 ------------------------------------------------------------------------
def test_rf58_exporta_todas_las_filas_y_neutraliza(app, cliente, datos):
    from plasea.servicios import alertas

    with app.app_context():
        corte = db.session.get(Corte, datos["corte_2025_1_c3"])
        alerta = db.session.scalar(
            select(Alerta).where(
                Alerta.corte_id == corte.id, Alerta.estado_alerta == "roja"
            )
        )
        estudiante = alerta.inscripcion.matricula_periodo.estudiante
        estudiante.nombres = '=HIPERVINCULO("x")'
        db.session.commit()
        resumen = alertas.resumen_corte(corte)
        periodo_id = corte.periodo_academico_id
    total = resumen["roja"] + resumen["amarilla"]
    assert total > 50  # más que una página
    iniciar(cliente, AUDITOR)
    respuesta = cliente.get(f"/exportacion/alertas.csv?periodo={periodo_id}&corte=3")
    assert respuesta.mimetype == "text/csv"
    assert "attachment" in respuesta.headers["Content-Disposition"]
    texto = respuesta.data.decode("utf-8-sig")
    lineas = texto.strip().split("\r\n")
    assert lineas[0].startswith(
        "Código;Estudiante;Correo;Asignatura;Nombre asignatura;Curso;Profesor"
    )
    assert len(lineas) == total + 1
    assert "'=HIPERVINCULO" in texto and ";=HIPERVINCULO" not in texto
    solo_rojas = cliente.get(
        f"/exportacion/alertas.csv?periodo={periodo_id}&corte=3&tipo=roja"
    ).data.decode("utf-8-sig")
    assert len(solo_rojas.strip().split("\r\n")) == resumen["roja"] + 1
    assert _evento(app, "exportacion") == 2


# --- RF-49 a RF-53 ----------------------------------------------------------------
def test_rf49_rf50_rf51_clasificacion_coherente(app, cliente, datos):
    from plasea.servicios import continuidad

    with app.app_context():
        periodo = db.session.scalar(
            select(PeriodoAcademico).where(PeriodoAcademico.identificador == "2025-2")
        )
        siguiente = continuidad.periodo_siguiente(periodo)
        assert siguiente.identificador == "2026-1"
        filas = continuidad.clasificar(periodo)
        inscritos = set(
            db.session.scalars(
                select(MatriculaPeriodo.estudiante_id).where(
                    MatriculaPeriodo.periodo_academico_id == periodo.id
                )
            )
        )
        en_siguiente = set(
            db.session.scalars(
                select(MatriculaPeriodo.estudiante_id).where(
                    MatriculaPeriodo.periodo_academico_id == siguiente.id
                )
            )
        )
        assert {f.estudiante_id for f in filas} == inscritos
        for f in filas:
            if f.clasificacion == continuidad.CONTINUA:
                assert f.estudiante_id in en_siguiente
            else:
                assert f.estudiante_id not in en_siguiente
        total = continuidad.indicador("t", filas)
        assert total.graduados > 0 and total.no_continuan > 0
        assert total.indice == Decimal(total.no_continuan) * 100 / Decimal(
            total.inscritos - total.graduados - total.aplazados
        )
        por_semestre = continuidad.por_grupo(filas, lambda f: f.semestre)
        assert sum(g.no_continuan for g in por_semestre) == total.no_continuan
        with pytest.raises(Exception, match="aún no tiene período siguiente"):
            continuidad.clasificar(
                db.session.scalar(
                    select(PeriodoAcademico).where(
                        PeriodoAcademico.identificador == "2026-2"
                    )
                )
            )
    iniciar(cliente, AUDITOR)
    pagina = cliente.get(f"/continuidad/?periodo={periodo.id}").get_data(as_text=True)
    assert "No continuidad 2025-2 → 2026-1" in pagina
    assert "Por semestre cursado" in pagina and "Por cohorte de ingreso" in pagina


def test_rf52_rf53_causa_con_historial_y_filtros(app, cliente, datos):
    from plasea.servicios import continuidad

    with app.app_context():
        periodo = db.session.scalar(
            select(PeriodoAcademico).where(PeriodoAcademico.identificador == "2025-2")
        )
        filas = continuidad.clasificar(periodo)
        no_continua = next(
            f for f in filas if f.clasificacion == continuidad.NO_CONTINUA
        )
        continua = next(f for f in filas if f.clasificacion == continuidad.CONTINUA)
        periodo_id = periodo.id
    iniciar(cliente, AUDITOR)
    url = f"/continuidad/matriculas/{no_continua.matricula_id}/causa"
    cliente.post(url, data={"causa": "economica"})
    cliente.post(url, data={"causa": "laboral"})
    repetida = cliente.post(url, data={"causa": "laboral"}, follow_redirects=True)
    assert "ya tiene registrada esa causa" in repetida.get_data(as_text=True)
    invalida = cliente.post(
        f"/continuidad/matriculas/{continua.matricula_id}/causa",
        data={"causa": "economica"},
        follow_redirects=True,
    )
    assert "Solo se registra la causa" in invalida.get_data(as_text=True)
    with app.app_context():
        assert db.session.scalar(select(func.count(RegistroCausaNoContinuidad.id))) == 2
        fila = next(
            f
            for f in continuidad.clasificar(
                db.session.get(PeriodoAcademico, periodo_id)
            )
            if f.matricula_id == no_continua.matricula_id
        )
        assert fila.causa_codigo == "laboral"  # la vigente es la última
    laboral = cliente.get(f"/continuidad/?periodo={periodo_id}&causa=laboral").get_data(
        as_text=True
    )
    assert no_continua.codigo in laboral and "1 estudiante(s)." in laboral
    sin_causa = cliente.get(
        f"/continuidad/?periodo={periodo_id}&causa=sin_causa"
    ).get_data(as_text=True)
    assert no_continua.codigo not in sin_causa


# --- RF-33 ------------------------------------------------------------------------
def test_rf33_historial_de_cambios_con_filtros(app, cliente, datos):
    with app.app_context():
        nota = db.session.scalar(select(NotaCorte).limit(1))
        ausencia = db.session.scalar(select(Ausencia).limit(1))
        profesor = nota.registrada_por_usuario_id
        db.session.add(
            HistorialNota(
                nota_corte_id=nota.id,
                nota_anterior=Decimal("2.0"),
                nota_nueva=nota.nota if nota.nota != Decimal("2.0") else Decimal("2.1"),
                motivo="Error de digitación",
                usuario_id=profesor,
            )
        )
        db.session.add(
            HistorialAusencia(
                ausencia_id=ausencia.id,
                ausente_anterior=False,
                ausente_nuevo=True,
                motivo="Se registró tarde la falta",
                usuario_id=profesor,
            )
        )
        db.session.commit()
        codigo_nota = nota.inscripcion.matricula_periodo.estudiante.codigo
        curso_nota = nota.inscripcion.curso_id
    iniciar(cliente, AUDITOR)
    todo = cliente.get("/registro/historial").get_data(as_text=True)
    assert "2 cambio(s)" in todo
    assert "Error de digitación" in todo and "Se registró tarde la falta" in todo
    assert "Presente" in todo and "Ausente" in todo
    por_estudiante = cliente.get(f"/registro/historial?estudiante={codigo_nota}")
    assert "Error de digitación" in por_estudiante.get_data(as_text=True)
    por_curso = cliente.get(f"/registro/historial?curso={curso_nota}").get_data(
        as_text=True
    )
    assert "Error de digitación" in por_curso
    manana = (dt.date.today() + dt.timedelta(days=2)).isoformat()
    futuro = cliente.get(f"/registro/historial?desde={manana}").get_data(as_text=True)
    assert "0 cambio(s)" in futuro
