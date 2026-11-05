"""Pruebas funcionales de RF-64 a RF-67 y de los cambios en RF-45, RF-48, RF-60 y RF-61.

Usan el generador de RF-25 con un volumen reducido y fuerzan una pérdida
reiterada conocida. Requieren URL_BASE_DATOS_PRUEBAS.
"""

from __future__ import annotations

from typing import Any

import pytest
from conftest import iniciar as _iniciar
from sqlalchemy import func, select

from plasea.modelos import (
    Alerta,
    Bitacora,
    Curso,
    Inscripcion,
    NotaCorte,
    PeriodoAcademico,
    TipoEventoBitacora,
    Usuario,
    db,
)

ADMIN, AUDITOR, PROFE, PROFE2 = (
    "admin@plasea.edu.co",
    "auditor@plasea.edu.co",
    "profe1@plasea.edu.co",
    "profe2@plasea.edu.co",
)
CLAVE_PROFESORES = "Profe123*"


def iniciar(cliente: Any, correo: str, contrasena: str | None = None) -> Any:
    """Cambia de usuario cerrando la sesión anterior."""
    cliente.post("/cerrar-sesion")
    if contrasena:
        return _iniciar(cliente, correo, contrasena)
    return _iniciar(cliente, correo)


@pytest.fixture()
def datos(app, crear_usuario):
    """Cuatro semestres de RF-25, un Auditor y una pérdida reiterada conocida."""
    from plasea.servicios import datos_prueba

    crear_usuario(ADMIN, rol="administrador_sistema")
    crear_usuario(AUDITOR, rol="auditor_academico", nombre="Auditora")
    with app.app_context():
        datos_prueba.generar(ADMIN, semilla=7, volumen=datos_prueba.Volumen(40, 8, 5))
        periodo = db.session.scalar(
            select(PeriodoAcademico).where(PeriodoAcademico.identificador == "2026-1")
        )
        cursos = db.session.scalars(
            select(Curso)
            .join(Usuario, Usuario.id == Curso.profesor_usuario_id)
            .where(Usuario.correo == PROFE, Curso.periodo_academico_id == periodo.id)
            .order_by(Curso.id)
        ).all()
        curso, inscripciones = next(
            (c, ins)
            for c in cursos
            for ins in [
                db.session.scalars(
                    select(Inscripcion)
                    .join(Alerta, Alerta.inscripcion_id == Inscripcion.id)
                    .where(Inscripcion.curso_id == c.id)
                    .distinct()
                    .limit(2)
                ).all()
            ]
            if len(ins) >= 2
        )
        marcada, no_marcada = inscripciones[0], inscripciones[1]
        _forzar(marcada.id, {1: (True, False), 2: (False, True)})
        _forzar(no_marcada.id, {1: (True, False)}, resto_verde=(2,))
        return {
            "curso": curso.id,
            "periodo": periodo.id,
            "marcada": marcada.id,
            "no_marcada": no_marcada.id,
            "estudiante": marcada.matricula_periodo.estudiante_id,
            "codigo": marcada.matricula_periodo.estudiante.codigo,
        }


def _forzar(inscripcion_id, rojos, resto_verde=()):
    """Deja la alerta en rojo en los cortes indicados con el motivo dado."""
    for alerta in db.session.scalars(
        select(Alerta).where(Alerta.inscripcion_id == inscripcion_id)
    ):
        numero = alerta.corte.numero
        if numero in rojos:
            alerta.estado_alerta = "roja"
            alerta.motivo_nota, alerta.motivo_inasistencia = rojos[numero]
        elif numero in resto_verde:
            alerta.estado_alerta = "verde"
            alerta.motivo_nota = alerta.motivo_inasistencia = False
    db.session.commit()


def _exportaciones(app: Any, entidad: str, entidad_id: int) -> int:
    with app.app_context():
        return db.session.scalar(
            select(func.count(Bitacora.id))
            .join(TipoEventoBitacora)
            .where(
                TipoEventoBitacora.codigo == "exportacion",
                Bitacora.entidad == entidad,
                Bitacora.entidad_id == entidad_id,
            )
        )


# --- RF-64 --------------------------------------------------------------------------
def test_rf64_marca_solo_a_quien_esta_en_rojo_en_los_cortes_1_y_2(app, datos):
    from plasea.servicios import perdida_reiterada

    with app.app_context():
        marca = perdida_reiterada.de_inscripcion(datos["marcada"])
        assert marca is not None
        assert (marca.corte_1.motivo, marca.corte_2.motivo) == ("nota", "inasistencia")
        assert perdida_reiterada.de_inscripcion(datos["no_marcada"]) is None
        assert datos["marcada"] in {
            p.inscripcion_id for p in perdida_reiterada.del_curso(datos["curso"])
        }


def test_rf64_se_actualiza_al_cambiar_las_alertas(app, datos):
    from plasea.servicios import perdida_reiterada

    with app.app_context():
        _forzar(datos["marcada"], {1: (True, False)}, resto_verde=(2,))
        assert perdida_reiterada.de_inscripcion(datos["marcada"]) is None


# --- RF-45 --------------------------------------------------------------------------
def test_rf45_detalle_muestra_grafica_y_perdida_reiterada(cliente, datos):
    iniciar(cliente, AUDITOR)
    pagina = cliente.get(f"/alertas/detalle/{datos['marcada']}?corte=2").get_data(
        as_text=True
    )
    assert "Pérdida reiterada" in pagina
    assert "Gráfica del estudiante en la asignatura" in pagina
    assert "Nota acumulada y nota requerida" in pagina
    assert "Inasistencia acumulada" in pagina
    sin_marca = cliente.get(f"/alertas/detalle/{datos['no_marcada']}?corte=2")
    assert "Pérdida reiterada" not in sin_marca.get_data(as_text=True)


# --- RF-48 --------------------------------------------------------------------------
def test_rf48_distribucion_coincide_con_la_lista_de_alertas(app, datos):
    from plasea.servicios import alertas, analitica

    with app.app_context():
        periodo = db.session.get(PeriodoAcademico, datos["periodo"])
        for d in analitica.distribucion_por_corte(
            periodo, analitica.FiltrosResultados()
        ):
            resumen = alertas.resumen_corte(d.corte)
            assert d.roja.total == resumen["roja"]
            assert d.amarilla.total == resumen["amarilla"]
            assert d.verde == resumen["verde"]
            _filas, total = analitica.resultados(d.corte, analitica.FiltrosResultados())
            assert d.total == total.inscritos
            assert d.perdidos.total == total.perdidos


def test_rf48_pantalla_incluye_grafica_y_exportar_pdf(cliente, datos):
    iniciar(cliente, AUDITOR)
    pagina = cliente.get(f"/alertas/resultados?periodo={datos['periodo']}").get_data(
        as_text=True
    )
    assert "Estudiantes por estado y motivo en cada corte" in pagina
    assert f"/exportacion/curso/{datos['curso']}" in pagina
    assert "data-autoenviar" in pagina


# --- RF-60 --------------------------------------------------------------------------
def test_rf60_imprimible_trae_grafica_y_marca(cliente, datos):
    iniciar(cliente, AUDITOR)
    pagina = cliente.get(f"/exportacion/historico/{datos['estudiante']}").get_data(
        as_text=True
    )
    assert "Pérdida reiterada" in pagina
    assert "Notas por corte e inasistencia" in pagina or "Nota de cada corte" in pagina


def test_rf61_historico_registra_el_estudiante(app, cliente, datos):
    iniciar(cliente, AUDITOR)
    cliente.get(f"/exportacion/historico/{datos['estudiante']}")
    assert _exportaciones(app, "estudiantes", datos["estudiante"]) == 1


# --- RF-65 --------------------------------------------------------------------------
def test_rf65_documento_del_auditor(app, cliente, datos):
    iniciar(cliente, AUDITOR)
    respuesta = cliente.get(f"/exportacion/curso/{datos['curso']}")
    pagina = respuesta.get_data(as_text=True)
    assert respuesta.status_code == 200
    for texto in (
        "Estadística del curso",
        "2026-1",
        "Fecha de generación",
        "Generado por",
        "Estudiantes con pérdida reiterada",
        datos["codigo"],
        "Por nota",
        "Por inasistencia",
    ):
        assert texto in pagina
    assert "barra-lateral" not in pagina and 'class="navbar' not in pagina
    assert _exportaciones(app, "cursos", datos["curso"]) == 1


def test_rf65_cifras_coinciden_con_resultados(app, cliente, datos):
    from plasea.servicios import analitica, estadistica_curso

    with app.app_context():
        curso = estadistica_curso.obtener_curso(datos["curso"])
        est = estadistica_curso.estadistica(curso)
        for corte, total in est.por_corte:
            _f, esperado = analitica.resultados(
                corte, analitica.FiltrosResultados(curso_id=curso.id)
            )
            assert (
                total.inscritos,
                total.aprobados,
                total.en_alerta,
                total.perdidos,
            ) == (
                esperado.inscritos,
                esperado.aprobados,
                esperado.en_alerta,
                esperado.perdidos,
            )


def test_rf65_solo_el_auditor(cliente, datos):
    iniciar(cliente, PROFE, CLAVE_PROFESORES)
    assert cliente.get(f"/exportacion/curso/{datos['curso']}").status_code == 403


# --- RF-66 --------------------------------------------------------------------------
def test_rf66_pantalla_del_profesor(cliente, datos):
    iniciar(cliente, PROFE, CLAVE_PROFESORES)
    respuesta = cliente.get(f"/graficos/cursos/{datos['curso']}?corte=2")
    pagina = respuesta.get_data(as_text=True)
    assert respuesta.status_code == 200
    for texto in (
        "Notas registradas por corte",
        "Carga hasta",
        "Definitivo",
        "Exportar PDF",
    ):
        assert texto in pagina
    assert "Roja" in pagina and "Por inasistencia" in pagina


def test_rf66_curso_ajeno_responde_403(cliente, datos):
    iniciar(cliente, PROFE2, CLAVE_PROFESORES)
    assert cliente.get(f"/graficos/cursos/{datos['curso']}").status_code == 403
    iniciar(cliente, AUDITOR)
    assert cliente.get(f"/graficos/cursos/{datos['curso']}").status_code == 403


def test_rf66_totales_y_valores_coinciden_con_rf27_y_rf34(app, datos):
    from plasea.servicios import (
        estadistica_profesor,
        registro_academico,
        seguimiento_profesor,
    )

    with app.app_context():
        curso = registro_academico.obtener_curso_propio(
            datos["curso"],
            db.session.scalar(select(Usuario.id).where(Usuario.correo == PROFE)),
        )
        corte = estadistica_profesor.corte_elegido(curso, 2)
        reporte = estadistica_profesor.reporte_curso(curso, corte)
        assert len(reporte.filas) == len(
            registro_academico.estudiantes_del_curso(curso.id)
        )
        assert reporte.avance.inscritos == len(reporte.filas)
        segui = {
            f.inscripcion_id: f
            for f in seguimiento_profesor.seguimiento_curso(curso, corte).filas
        }
        for fila in reporte.filas:
            if fila.nota_corte is not None:
                assert fila.estado == segui[fila.inscripcion_id].estado
            assert fila.nota_acumulada == segui[fila.inscripcion_id].nota_acumulada
            assert (
                fila.porcentaje_inasistencia
                == segui[fila.inscripcion_id].porcentaje_inasistencia
            )
        con_nota = db.session.scalar(
            select(func.count(NotaCorte.id))
            .join(Inscripcion, Inscripcion.id == NotaCorte.inscripcion_id)
            .where(Inscripcion.curso_id == curso.id, NotaCorte.corte_id == corte.id)
        )
        assert reporte.avance.con_nota == con_nota


def test_rf66_sin_nota_en_el_corte_se_evalua_por_inasistencia(app, datos):
    from plasea.servicios import estadistica_profesor, registro_academico

    with app.app_context():
        curso = registro_academico.obtener_curso_propio(
            datos["curso"],
            db.session.scalar(select(Usuario.id).where(Usuario.correo == PROFE)),
        )
        corte = estadistica_profesor.corte_elegido(curso, 1)
        db.session.execute(
            NotaCorte.__table__.delete().where(
                NotaCorte.inscripcion_id == datos["no_marcada"],
                NotaCorte.corte_id == corte.id,
            )
        )
        db.session.commit()
        fila = next(
            f
            for f in estadistica_profesor.reporte_curso(curso, corte).filas
            if f.inscripcion_id == datos["no_marcada"]
        )
        assert fila.nota_corte is None
        assert not fila.motivo_nota
        assert fila.estado in ("roja", "amarilla", "sin_nota")


# --- RF-67 --------------------------------------------------------------------------
def test_rf67_documento_del_profesor(app, cliente, datos):
    iniciar(cliente, PROFE, CLAVE_PROFESORES)
    respuesta = cliente.get(f"/exportacion/reporte-curso/{datos['curso']}?corte=2")
    pagina = respuesta.get_data(as_text=True)
    assert respuesta.status_code == 200
    for texto in (
        "Estadística de reporte del curso",
        "Fecha de generación",
        "Generado por",
        "Estado de las alertas",
        "Nota del corte",
        "Requerida",
        datos["codigo"],
    ):
        assert texto in pagina
    assert "@" not in pagina.split("<main")[1].split("</main>")[0].replace("@page", "")
    assert _exportaciones(app, "cursos", datos["curso"]) == 1


def test_rf67_curso_ajeno_responde_403(cliente, datos):
    iniciar(cliente, PROFE2, CLAVE_PROFESORES)
    assert (
        cliente.get(f"/exportacion/reporte-curso/{datos['curso']}").status_code == 403
    )
    iniciar(cliente, AUDITOR)
    assert (
        cliente.get(f"/exportacion/reporte-curso/{datos['curso']}").status_code == 403
    )
