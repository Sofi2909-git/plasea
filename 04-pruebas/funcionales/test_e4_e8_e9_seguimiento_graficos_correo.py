"""Pruebas funcionales de RF-34, RF-54 a RF-56 y RF-57.

Usan el generador de RF-25 con un volumen reducido (4 semestres) para comparar
las cifras de cada pantalla con su fuente (RF-40 a RF-44, RF-49 y RF-51).
Requieren URL_BASE_DATOS_PRUEBAS.
"""

from __future__ import annotations

from typing import Any

import pytest
from conftest import iniciar as _iniciar
from sqlalchemy import select, update

from plasea.modelos import Alerta, Corte, Curso, PeriodoAcademico, Usuario, db

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
    """Cuatro semestres generados con RF-25 y un Auditor académico."""
    from plasea.servicios import datos_prueba

    crear_usuario(ADMIN, rol="administrador_sistema")
    crear_usuario(AUDITOR, rol="auditor_academico", nombre="Auditora")
    with app.app_context():
        datos_prueba.generar(ADMIN, semilla=7, volumen=datos_prueba.Volumen(40, 8, 5))


def _periodo(identificador: str) -> PeriodoAcademico:
    return db.session.scalar(
        select(PeriodoAcademico).where(PeriodoAcademico.identificador == identificador)
    )


def _curso_de(correo: str, identificador: str) -> Curso:
    return db.session.scalar(
        select(Curso)
        .join(Usuario, Usuario.id == Curso.profesor_usuario_id)
        .where(
            Usuario.correo == correo,
            Curso.periodo_academico_id == _periodo(identificador).id,
        )
        .order_by(Curso.id)
        .limit(1)
    )


def _decimal(valor: Any, decimales: int) -> str:
    return f"{valor:.{decimales}f}".replace(".", ",")


# --- Permisos ---------------------------------------------------------------------
def test_permisos_por_rol(app, cliente, datos):
    with app.app_context():
        curso = _curso_de(PROFE, "2026-1").id
    iniciar(cliente, PROFE, CLAVE_PROFESORES)
    assert cliente.get("/graficos/").status_code == 403
    assert cliente.get(f"/registro/cursos/{curso}/seguimiento").status_code == 200
    iniciar(cliente, PROFE2, CLAVE_PROFESORES)
    assert cliente.get(f"/registro/cursos/{curso}/seguimiento").status_code == 403
    iniciar(cliente, AUDITOR)
    assert cliente.get(f"/registro/cursos/{curso}/seguimiento").status_code == 403
    assert cliente.get("/graficos/").status_code == 200


# --- RF-34 ------------------------------------------------------------------------
def test_rf34_coincide_con_las_alertas(app, cliente, datos):
    from plasea.servicios import alertas, seguimiento_profesor

    with app.app_context():
        # Corte cerrado: valores definitivos guardados (RF-43).
        curso = _curso_de(PROFE, "2026-1")
        corte = next(c for c in curso.periodo_academico.cortes if c.numero == 2)
        guardadas = {
            a.inscripcion_id: a
            for a in db.session.scalars(
                select(Alerta).where(
                    Alerta.corte_id == corte.id,
                    Alerta.inscripcion_id.in_([i.id for i in curso.inscripciones]),
                )
            )
        }
        datos_vista = seguimiento_profesor.seguimiento_curso(curso, corte)
        assert datos_vista.definitivo
        assert len(datos_vista.filas) == len(guardadas)
        for fila in datos_vista.filas:
            alerta = guardadas[fila.inscripcion_id]
            assert fila.estado == alerta.estado_alerta
            assert fila.porcentaje_inasistencia == alerta.porcentaje_inasistencia
            assert fila.nota_acumulada == alerta.nota_acumulada
        # Orden por severidad: rojas, amarillas y verdes.
        severidades = [
            {"roja": 0, "amarilla": 1, "verde": 2}[f.estado] for f in datos_vista.filas
        ]
        assert severidades == sorted(severidades)
        roja = next((f for f in datos_vista.filas if f.estado == "roja"), None)
        curso_id, numero = curso.id, corte.numero

        # Corte abierto: cálculo en vivo igual al de RF-43.
        actual = _curso_de(PROFE, "2026-2")
        abierto = seguimiento_profesor.corte_por_defecto(actual)
        if abierto is not None and abierto.cerrado_en is None:
            vivo = {i: v for i, _, v in alertas.evaluar(abierto, [actual.id])}
            vista = seguimiento_profesor.seguimiento_curso(actual, abierto)
            assert not vista.definitivo
            assert {f.inscripcion_id: f.estado for f in vista.filas} == {
                i: v["estado_alerta"] for i, v in vivo.items()
            }

    iniciar(cliente, PROFE, CLAVE_PROFESORES)
    pagina = cliente.get(
        f"/registro/cursos/{curso_id}/seguimiento?corte={numero}"
    ).get_data(as_text=True)
    assert "Definitivo" in pagina
    if roja is not None:
        assert roja.nombres in pagina
        assert _decimal(roja.porcentaje_inasistencia, 1) + " %" in pagina


# --- RF-54 a RF-56 ----------------------------------------------------------------
def test_rf54_rf55_rf56_cifras_del_tablero(app, cliente, datos):
    from plasea.servicios import alertas, continuidad, graficos

    with app.app_context():
        periodo = _periodo("2026-1")
        semaforo = graficos.semaforo_por_corte(periodo)
        assert len(semaforo) == 3
        for fila in semaforo:  # RF-54 coincide con RF-44
            resumen = alertas.resumen_corte(fila.corte)
            assert (fila.roja, fila.amarilla, fila.verde) == (
                resumen["roja"],
                resumen["amarilla"],
                resumen["verde"],
            )
        corte3 = semaforo[2]

        comparativo = graficos.comparativo_periodos()  # RF-55 coincide con RF-49
        assert [f.periodo.identificador for f in comparativo] == [
            "2025-1",
            "2025-2",
            "2026-1",
            "2026-2",
        ]
        for fila in comparativo[:-1]:
            total = continuidad.indicador("", continuidad.clasificar(fila.periodo))
            assert (fila.inscritos, fila.continuan) == (
                total.inscritos,
                total.continuan,
            )
        assert comparativo[-1].continuan is None

        total, grupos = graficos.no_continuidad_por_semestre(periodo)  # RF-56
        assert [g.etiqueta for g in grupos] == [str(s) for s in range(1, 11)]
        assert sum(g.no_continuan for g in grupos) == total.no_continuan
        assert sum(g.base for g in grupos) == total.base
        periodo_id = periodo.id

    iniciar(cliente, AUDITOR)
    pagina = cliente.get(
        f"/graficos/?periodo={periodo_id}&corte=3&periodo_nc={periodo_id}"
    ).get_data(as_text=True)
    assert f"<strong>{corte3.roja}</strong>" in pagina
    assert f"<strong>{corte3.verde}</strong>" in pagina
    assert "2026-1 → 2026-2" in pagina
    assert "Sem. 10" in pagina


# --- RF-57 ------------------------------------------------------------------------
def test_rf57_resumen_una_vez_por_corte(app, datos, monkeypatch):
    from plasea.servicios import alertas, notificaciones

    enviados: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        notificaciones,
        "enviar_correo",
        lambda destino, asunto, cuerpo: enviados.append((destino, asunto, cuerpo)),
    )
    with app.app_context():
        assert notificaciones.enviar_resumenes_pendientes() == []  # históricos
        periodo = _periodo("2026-1")
        corte1, corte2 = sorted(periodo.cortes, key=lambda c: c.numero)[:2]

        # Alertas nuevas del corte 2: en alerta ahora y no en el corte 1.
        previas = set(
            db.session.scalars(
                select(Alerta.inscripcion_id).where(
                    Alerta.corte_id == corte1.id,
                    Alerta.estado_alerta.in_(alertas.TIPOS),
                )
            )
        )
        actuales = set(
            db.session.scalars(
                select(Alerta.inscripcion_id).where(
                    Alerta.corte_id == corte2.id,
                    Alerta.estado_alerta.in_(alertas.TIPOS),
                )
            )
        )
        assert notificaciones.alertas_nuevas(corte2) == len(actuales - previas)
        assert notificaciones.alertas_nuevas(corte1) == len(previas)

        db.session.execute(
            update(Corte)
            .where(Corte.id == corte2.id)
            .values(aviso_resumen_enviado_en=None)
        )
        db.session.commit()
        resumen = notificaciones.resumen_cierre(corte2)
        enviados_ahora = notificaciones.enviar_resumenes_pendientes()
        assert enviados_ahora == ["2026-1 corte 2"]
        destino, asunto, cuerpo = enviados[0]
        assert destino == AUDITOR and "corte 2 de 2026-1" in asunto
        assert f"Alertas rojas: {resumen.rojas}" in cuerpo
        assert f"Alertas amarillas: {resumen.amarillas}" in cuerpo
        assert (
            f"riesgo alto (2 o más asignaturas en alerta): {resumen.riesgo_alto}"
            in (cuerpo)
        )
        assert f"/alertas/?periodo={periodo.id}&corte=2" in cuerpo
        db.session.refresh(corte2)
        assert corte2.aviso_resumen_enviado_en is not None

        # Idempotente: no se repite.
        assert notificaciones.enviar_resumenes_pendientes() == []
        assert len(enviados) == len(notificaciones.destinatarios())

        # Corte abierto: nunca se envía.
        actual = _periodo("2026-2")
        abiertos = [c for c in actual.cortes if c.cerrado_en is None]
        for corte in abiertos:
            assert notificaciones.enviar_resumen(corte) is False
            db.session.refresh(corte)
            assert corte.aviso_resumen_enviado_en is None
