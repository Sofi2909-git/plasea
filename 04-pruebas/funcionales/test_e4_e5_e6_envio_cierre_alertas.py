"""Pruebas funcionales de RF-30 a RF-32 y RF-35 a RF-44.

Escenario con fechas relativas a hoy: el período empezó hace 70 días, así que el
corte 2 terminó ayer (plazo de carga abierto 2 días más y de corrección 6) y el
corte 1 tiene vencido su límite de corrección. profe1 dicta T01 (3 estudiantes)
y profe2 dicta T02 (1 estudiante). Requieren URL_BASE_DATOS_PRUEBAS.
"""

from __future__ import annotations

import datetime as dt
import time
from decimal import Decimal
from typing import Any

import pytest
from conftest import iniciar as _iniciar
from sqlalchemy import func, select

from plasea.modelos import (
    Alerta,
    Asignatura,
    Ausencia,
    Bitacora,
    BloqueHorario,
    Corte,
    Curso,
    EstadoEstudiante,
    Estudiante,
    HistorialAusencia,
    HistorialEstadoEstudiante,
    HistorialNota,
    Inscripcion,
    MatriculaPeriodo,
    NotaCorte,
    PeriodoAcademico,
    ProgramaAcademico,
    ReaperturaCurso,
    RegistroCursoCorte,
    SesionClase,
    TipoEventoBitacora,
    db,
)

PROFE, OTRO = "profe1@plasea.edu.co", "profe2@plasea.edu.co"
AUDITOR, ADMIN = "auditor@plasea.edu.co", "admin@plasea.edu.co"
D = Decimal


def iniciar(cliente: Any, correo: str) -> Any:
    """Cambia de usuario: cierra la sesión actual y abre la nueva."""
    cliente.post("/cerrar-sesion")
    return _iniciar(cliente, correo)


def _contar(app: Any, modelo: Any, *condiciones: Any) -> int:
    with app.app_context():
        return db.session.scalar(
            select(func.count()).select_from(modelo).where(*condiciones)
        )


def _evento(app: Any, codigo: str) -> int:
    with app.app_context():
        return db.session.scalar(
            select(func.count(Bitacora.id))
            .join(TipoEventoBitacora)
            .where(TipoEventoBitacora.codigo == codigo)
        )


@pytest.fixture()
def esc(app, crear_usuario):
    """Período con el corte 2 recién terminado y dos cursos."""
    from plasea.servicios import calendario, periodos
    from plasea.servicios.comunes import ahora

    profe = crear_usuario(PROFE, rol="profesor", nombre="Profesor Uno")
    otro = crear_usuario(OTRO, rol="profesor", nombre="Profesor Dos")
    auditor = crear_usuario(AUDITOR, rol="auditor_academico", nombre="Auditora")
    hoy = ahora().date()
    inicio = hoy - dt.timedelta(days=70)
    datos: dict[str, Any] = {"hoy": hoy, "profe": profe, "auditor": auditor}
    with app.app_context():
        programa = db.session.scalar(select(ProgramaAcademico.id))
        activo = db.session.scalar(
            select(EstadoEstudiante.id).where(EstadoEstudiante.codigo == "activo")
        )
        periodo = PeriodoAcademico(
            identificador="2026-2",
            fecha_inicio=inicio,
            fecha_fin=inicio + dt.timedelta(days=111),
            en_curso_marca=1,
        )
        db.session.add(periodo)
        db.session.flush()
        for d in periodos.cortes_sugeridos(periodo):
            db.session.add(Corte(periodo_academico_id=periodo.id, **d.__dict__))
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
        inscripciones = {}
        for numero, (nombre, curso) in enumerate(
            (
                ("Ana Rojas", "T01"),
                ("Bruno Celis", "T01"),
                ("Carla Duarte", "T01"),
                ("Diego León", "T02"),
            ),
            start=1,
        ):
            estudiante = Estudiante(
                codigo=f"2024100{numero}",
                nombres=nombre,
                correo=f"e{numero}@estudiantes.co",
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
            inscripcion = Inscripcion(
                matricula_periodo_id=matricula.id,
                curso_id=cursos[curso],
                periodo_academico_id=periodo.id,
            )
            db.session.add(inscripcion)
            db.session.flush()
            inscripciones[nombre.split()[0]] = inscripcion.id
        db.session.commit()
        datos["cortes"] = {
            c.numero: c.id
            for c in db.session.scalars(
                select(Corte).where(Corte.periodo_academico_id == periodo.id)
            )
        }
        datos["periodo"] = periodo.id
    datos.update(cursos=cursos, ins=inscripciones)
    return datos


def _completar(app, esc, notas_c2=None, ausencias_carla=5, registrar=True):
    """Notas del corte 1 y 2 de T01 y asistencia registrada hasta hoy.

    Ana: 3,0 y 2,0 (roja por nota). Bruno: 3,0 y 3,2 (amarilla por nota).
    Carla: 4,0 y 4,5 con ausencias (amarilla por ritmo de inasistencia).
    """
    notas_c2 = notas_c2 or {"Ana": "2.0", "Bruno": "3.2", "Carla": "4.5"}
    notas_c1 = {"Ana": "3.0", "Bruno": "3.0", "Carla": "4.0"}
    with app.app_context():
        sesiones = db.session.scalars(
            select(SesionClase)
            .where(
                SesionClase.curso_id == esc["cursos"]["T01"],
                SesionClase.fecha < esc["hoy"],
            )
            .order_by(SesionClase.fecha)
        ).all()
        inicio_c2 = db.session.get(Corte, esc["cortes"][2]).fecha_inicio
        en_corte2 = [s.id for s in sesiones if s.fecha >= inicio_c2][:ausencias_carla]
        for sesion in sesiones:
            if registrar:
                sesion.asistencia_registrada_por_usuario_id = esc["profe"]
                sesion.asistencia_registrada_en = dt.datetime.combine(
                    sesion.fecha, dt.time(9)
                )
            if sesion.id in en_corte2:
                db.session.add(
                    Ausencia(
                        sesion_clase_id=sesion.id,
                        inscripcion_id=esc["ins"]["Carla"],
                        ausente=True,
                        registrada_por_usuario_id=esc["profe"],
                    )
                )
        for numero, notas in ((1, notas_c1), (2, notas_c2)):
            for nombre, valor in notas.items():
                db.session.add(
                    NotaCorte(
                        inscripcion_id=esc["ins"][nombre],
                        corte_id=esc["cortes"][numero],
                        nota=D(valor),
                        registrada_por_usuario_id=esc["profe"],
                    )
                )
        db.session.commit()


def _alerta(app, esc, nombre, numero=2):
    with app.app_context():
        alerta = db.session.scalar(
            select(Alerta).where(
                Alerta.inscripcion_id == esc["ins"][nombre],
                Alerta.corte_id == esc["cortes"][numero],
            )
        )
        if alerta is not None:
            db.session.expunge(alerta)
        return alerta


def _enviar(cliente, esc, numero=2, curso="T01"):
    return cliente.post(
        f"/registro/cursos/{esc['cursos'][curso]}/cortes/{numero}/enviar",
        follow_redirects=True,
    )


# --- RF-30 ----------------------------------------------------------------------
def test_rf30_lista_lo_pendiente_y_no_envia(app, cliente, esc):
    iniciar(cliente, PROFE)
    pagina = cliente.get(f"/registro/cursos/{esc['cursos']['T01']}/cortes/2/notas")
    assert "Todavía no se puede enviar" in pagina.get_data(as_text=True)
    respuesta = _enviar(cliente, esc).get_data(as_text=True)
    assert "No se envió. Falta: 3 estudiante(s) sin nota" in respuesta
    assert "sin asistencia registrada" in respuesta
    assert _contar(app, RegistroCursoCorte, RegistroCursoCorte.estado == "enviado") == 0


def test_rf30_rf43_enviar_calcula_alertas(app, cliente, esc):
    _completar(app, esc)
    iniciar(cliente, PROFE)
    respuesta = _enviar(cliente, esc).get_data(as_text=True)
    assert "Se envió el registro del corte 2" in respuesta
    assert _contar(app, RegistroCursoCorte, RegistroCursoCorte.estado == "enviado") == 1
    assert _evento(app, "envio_registro") == 1
    ana, bruno, carla = (_alerta(app, esc, n) for n in ("Ana", "Bruno", "Carla"))
    assert (ana.estado_alerta, ana.motivo_nota, ana.motivo_inasistencia) == (
        "roja",
        True,
        False,
    )
    assert ana.nota_acumulada == D("1.50")  # 0,9 + 0,6
    assert ana.nota_requerida == D("3.75")  # (3,0 - 1,5) / 0,4
    assert (bruno.estado_alerta, bruno.motivo_nota) == ("amarilla", True)
    assert carla.estado_alerta == "amarilla" and carla.motivo_inasistencia
    assert carla.horas_ausentes == 10 and not carla.definitiva
    assert carla.porcentaje_ritmo >= D("20")


# --- RF-31 y RF-32 ----------------------------------------------------------------
def test_rf32_tras_el_envio_el_borrador_queda_bloqueado(app, cliente, esc):
    _completar(app, esc)
    iniciar(cliente, PROFE)
    _enviar(cliente, esc)
    respuesta = cliente.post(
        f"/registro/cursos/{esc['cursos']['T01']}/cortes/2/notas",
        data={f"nota-{esc['ins']['Ana']}": "4,0"},
        follow_redirects=True,
    ).get_data(as_text=True)
    assert "ya se envió" in respuesta
    with app.app_context():
        assert db.session.scalar(
            select(NotaCorte.nota).where(
                NotaCorte.inscripcion_id == esc["ins"]["Ana"],
                NotaCorte.corte_id == esc["cortes"][2],
            )
        ) == D("2.0")


def _corregir_notas(cliente, esc, cambios):
    datos = {}
    for nombre, (nota, motivo) in cambios.items():
        datos[f"nota-{esc['ins'][nombre]}"] = nota
        datos[f"motivo-{esc['ins'][nombre]}"] = motivo
    return cliente.post(
        f"/registro/cursos/{esc['cursos']['T01']}/cortes/2/correccion",
        data=datos,
        follow_redirects=True,
    )


def test_rf31_correccion_de_nota_exige_motivo_y_guarda_historial(app, cliente, esc):
    _completar(app, esc)
    iniciar(cliente, PROFE)
    _enviar(cliente, esc)
    sin_motivo = _corregir_notas(cliente, esc, {"Ana": ("3,5", "")}).get_data(
        as_text=True
    )
    assert "Escriba el motivo" in sin_motivo
    assert _contar(app, HistorialNota) == 0
    _corregir_notas(
        cliente, esc, {"Ana": ("3,2", "Error de digitación en la planilla")}
    )
    with app.app_context():
        historial = db.session.scalar(select(HistorialNota))
        assert (historial.nota_anterior, historial.nota_nueva) == (D("2.0"), D("3.2"))
        assert historial.motivo == "Error de digitación en la planilla"
        assert historial.usuario_id == esc["profe"]
    assert _alerta(app, esc, "Ana").estado_alerta == "amarilla"  # recalculada
    assert _evento(app, "correccion") == 1


def test_rf31_correccion_de_asistencia_con_motivo(app, cliente, esc):
    _completar(app, esc)
    iniciar(cliente, PROFE)
    _enviar(cliente, esc)
    with app.app_context():
        sesion = db.session.scalar(
            select(Ausencia.sesion_clase_id)
            .where(Ausencia.inscripcion_id == esc["ins"]["Carla"])
            .limit(1)
        )
    url = f"/registro/cursos/{esc['cursos']['T01']}/sesiones/{sesion}/correccion"
    sin_motivo = cliente.post(url, data={"ausentes": []}, follow_redirects=True)
    assert "Escriba el motivo" in sin_motivo.get_data(as_text=True)
    cliente.post(url, data={"ausentes": [], "motivo": "Llegó con excusa médica"})
    with app.app_context():
        assert db.session.scalar(select(func.count(HistorialAusencia.id))) == 1
        assert (
            db.session.scalar(
                select(Ausencia.ausente).where(Ausencia.sesion_clase_id == sesion)
            )
            is False
        )
    assert _alerta(app, esc, "Carla").horas_ausentes == 8


def test_rf32_correccion_sin_enviar_o_tras_cerrar_se_rechaza(app, cliente, esc):
    _completar(app, esc)
    iniciar(cliente, PROFE)
    sin_enviar = _corregir_notas(cliente, esc, {"Ana": ("3,5", "Motivo suficiente")})
    assert "aún no se ha enviado" in sin_enviar.get_data(as_text=True)
    _enviar(cliente, esc)
    from plasea.servicios import cierre_cortes

    with app.app_context():
        corte = db.session.get(Corte, esc["cortes"][2])
        corte.cerrado_en = dt.datetime.now()
        corte.tipo_cierre = "automatico"
        db.session.commit()
        assert cierre_cortes  # el cierre real se prueba en RF-36
    cerrado = _corregir_notas(cliente, esc, {"Ana": ("3,5", "Motivo suficiente")})
    assert "está cerrado" in cerrado.get_data(as_text=True)
    assert _contar(app, HistorialNota) == 0


# --- RF-35 y RF-36 ----------------------------------------------------------------
def test_rf35_seguimiento_con_filtro_de_pendientes(app, cliente, esc):
    _completar(app, esc)
    iniciar(cliente, PROFE)
    _enviar(cliente, esc)
    iniciar(cliente, AUDITOR)
    pagina = cliente.get("/cortes/?corte=2").get_data(as_text=True)
    assert "Profesor Uno" in pagina and "Profesor Dos" in pagina
    assert "Enviado" in pagina and "Pendiente" in pagina
    pendientes = cliente.get("/cortes/?corte=2&pendientes=1").get_data(as_text=True)
    assert "Profesor Dos" in pendientes and "Profesor Uno" not in pendientes


def test_rf35_solo_auditor(cliente, esc):
    iniciar(cliente, PROFE)
    assert cliente.get("/cortes/").status_code == 403
    assert cliente.get("/alertas/").status_code == 403


def test_rf36_cierre_manual(app, cliente, esc):
    _completar(app, esc)
    iniciar(cliente, PROFE)
    _enviar(cliente, esc)
    iniciar(cliente, AUDITOR)
    no_iniciado = cliente.post(
        f"/cortes/{esc['cortes'][3]}/cerrar", follow_redirects=True
    )
    assert "se puede cerrar desde esa fecha" in no_iniciado.get_data(as_text=True)
    respuesta = cliente.post(
        f"/cortes/{esc['cortes'][2]}/cerrar", follow_redirects=True
    )
    assert "1 curso(s) enviados, 1 sin registro" in respuesta.get_data(as_text=True)
    with app.app_context():
        corte = db.session.get(Corte, esc["cortes"][2])
        assert (
            corte.tipo_cierre == "manual"
            and corte.cerrado_por_usuario_id == esc["auditor"]
        )
        estados = dict(
            db.session.execute(
                select(RegistroCursoCorte.curso_id, RegistroCursoCorte.estado).where(
                    RegistroCursoCorte.corte_id == corte.id
                )
            ).all()
        )
    assert estados == {
        esc["cursos"]["T01"]: "cerrado",
        esc["cursos"]["T02"]: "sin_registro",
    }
    assert _alerta(app, esc, "Ana").definitiva  # pasa a definitiva
    assert _evento(app, "cierre_corte") == 1
    # Ningún profesor modifica el corte cerrado.
    iniciar(cliente, PROFE)
    bloqueada = _corregir_notas(cliente, esc, {"Ana": ("3,5", "Motivo suficiente")})
    assert "está cerrado" in bloqueada.get_data(as_text=True)


# --- RF-37 ------------------------------------------------------------------------
def test_rf37_cierre_automatico_idempotente_y_comando(app, esc):
    from plasea.servicios import cierre_cortes

    with app.app_context():
        cerrados = cierre_cortes.cerrar_vencidos()
        assert cerrados == ["2026-2 corte 1"]
        assert cierre_cortes.cerrar_vencidos() == []  # idempotente
        corte = db.session.get(Corte, esc["cortes"][1])
        assert (
            corte.tipo_cierre == "automatico" and corte.cerrado_por_usuario_id is None
        )
        assert corte.aviso_resumen_enviado_en is None  # lo envía RF-57
    salida = app.test_cli_runner().invoke(args=["cerrar-cortes-vencidos"])
    assert "No hay cortes vencidos" in salida.output


# --- RF-38 y RF-39 ----------------------------------------------------------------
def _cerrar_corte_2(app, cliente, esc):
    _completar(app, esc)
    iniciar(cliente, PROFE)
    _enviar(cliente, esc)
    iniciar(cliente, AUDITOR)
    cliente.post(f"/cortes/{esc['cortes'][2]}/cerrar")
    with app.app_context():
        return db.session.scalar(
            select(RegistroCursoCorte.id).where(
                RegistroCursoCorte.curso_id == esc["cursos"]["T01"],
                RegistroCursoCorte.corte_id == esc["cortes"][2],
            )
        )


def test_rf38_reapertura_con_motivo_solo_modifica_lo_existente(app, cliente, esc):
    registro = _cerrar_corte_2(app, cliente, esc)
    sin_motivo = cliente.post(
        f"/cortes/registros/{registro}/reabrir", data={"motivo": "corto"}
    )
    assert "de 10 a 500 caracteres" in sin_motivo.get_data(as_text=True)
    cliente.post(
        f"/cortes/registros/{registro}/reabrir",
        data={"motivo": "Falla del servidor durante la carga"},
    )
    assert _contar(app, ReaperturaCurso, ReaperturaCurso.cerrada_en.is_(None)) == 1
    assert _evento(app, "reapertura") == 1
    iniciar(cliente, PROFE)
    _corregir_notas(
        cliente, esc, {"Bruno": ("3,6", "Nota mal transcrita por la falla")}
    )
    with app.app_context():
        historial = db.session.scalar(select(HistorialNota))
        assert historial.reapertura_curso_id is not None
    # No permite crear registros: marcar como ausente a quien no tenía ausencia.
    with app.app_context():
        sesion = db.session.scalar(
            select(SesionClase.id)
            .where(
                SesionClase.curso_id == esc["cursos"]["T01"],
                SesionClase.fecha
                >= db.session.get(Corte, esc["cortes"][2]).fecha_inicio,
            )
            .order_by(SesionClase.fecha)
        )
    respuesta = cliente.post(
        f"/registro/cursos/{esc['cursos']['T01']}/sesiones/{sesion}/correccion",
        data={
            "ausentes": [str(esc["ins"]["Ana"])],
            "motivo": "Corrección en reapertura",
        },
        follow_redirects=True,
    )
    assert "no se crean registros nuevos" in respuesta.get_data(as_text=True)


def test_rf39_cerrar_reapertura_bloquea_y_recalcula(app, cliente, esc):
    registro = _cerrar_corte_2(app, cliente, esc)
    cliente.post(
        f"/cortes/registros/{registro}/reabrir",
        data={"motivo": "Falla del servidor durante la carga"},
    )
    with app.app_context():
        reapertura_id = db.session.scalar(select(ReaperturaCurso.id))
    iniciar(cliente, PROFE)
    _corregir_notas(cliente, esc, {"Ana": ("4,0", "Nota mal transcrita por la falla")})
    iniciar(cliente, AUDITOR)
    cliente.post(f"/cortes/reaperturas/{reapertura_id}/cerrar")
    assert _contar(app, ReaperturaCurso, ReaperturaCurso.cerrada_en.is_(None)) == 0
    assert _evento(app, "cierre_reapertura") == 1
    alerta = _alerta(app, esc, "Ana")
    assert alerta.definitiva and alerta.nota_corte == D("4.0")
    iniciar(cliente, PROFE)
    bloqueada = _corregir_notas(cliente, esc, {"Ana": ("4,5", "Otro cambio tardío")})
    assert "está cerrado" in bloqueada.get_data(as_text=True)


# --- RF-44 ------------------------------------------------------------------------
def test_rf44_lista_por_severidad_con_filtros_y_correo(app, cliente, esc):
    _completar(app, esc)
    iniciar(cliente, PROFE)
    _enviar(cliente, esc)
    iniciar(cliente, AUDITOR)
    pagina = cliente.get("/alertas/?corte=2").get_data(as_text=True)
    assert "Provisionales" in pagina
    assert pagina.index("Ana Rojas") < pagina.index("Bruno Celis")  # roja antes
    assert "e1@estudiantes.co" in pagina
    solo_rojas = cliente.get("/alertas/?corte=2&tipo=roja").get_data(as_text=True)
    assert "Ana Rojas" in solo_rojas and "Bruno Celis" not in solo_rojas
    inasistencia = cliente.get("/alertas/?corte=2&motivo=inasistencia").get_data(
        as_text=True
    )
    assert "Carla Duarte" in inasistencia and "Ana Rojas" not in inasistencia
    riesgo = cliente.get("/alertas/?corte=2&riesgo=1").get_data(as_text=True)
    assert "No hay alertas con estos filtros" in riesgo  # una sola asignatura


def test_rf44_riesgo_alto_con_dos_asignaturas(app, esc):
    from plasea.servicios import alertas

    with app.app_context():
        corte = db.session.get(Corte, esc["cortes"][2])
        matricula = db.session.scalar(
            select(Inscripcion.matricula_periodo_id).where(
                Inscripcion.id == esc["ins"]["Ana"]
            )
        )
        segunda = Asignatura(
            codigo="ISI602",
            nombre="Bases de Datos II",
            programa_academico_id=db.session.scalar(select(ProgramaAcademico.id)),
            creditos=3,
            horas_semanales=3,
            nivel=6,
        )
        db.session.add(segunda)
        db.session.flush()
        curso = Curso(
            asignatura_id=segunda.id,
            periodo_academico_id=corte.periodo_academico_id,
            codigo="T01",
            profesor_usuario_id=esc["profe"],
        )
        db.session.add(curso)
        db.session.flush()
        otra = Inscripcion(
            matricula_periodo_id=matricula,
            curso_id=curso.id,
            periodo_academico_id=corte.periodo_academico_id,
        )
        db.session.add(otra)
        db.session.flush()
        for inscripcion in (esc["ins"]["Ana"], otra.id):
            db.session.add(
                NotaCorte(
                    inscripcion_id=inscripcion,
                    corte_id=corte.id,
                    nota=D("2.5"),
                    registrada_por_usuario_id=esc["profe"],
                )
            )
        alertas.recalcular(corte)
        db.session.commit()
        pagina, en_riesgo = alertas.listar_alertas(
            corte, alertas.FiltrosAlertas(solo_riesgo_alto=True)
        )
        assert {a.inscripcion_id for a in pagina.items} == {esc["ins"]["Ana"], otra.id}
        assert len(en_riesgo) == 1
        assert alertas.resumen_corte(corte)["riesgo_alto"] == 1


def test_rf44_responde_en_menos_de_2_segundos_con_2000_alertas(app, crear_usuario):
    from plasea.servicios import alertas, datos_prueba

    crear_usuario(ADMIN, rol="administrador_sistema")
    with app.app_context():
        datos_prueba.generar(
            ADMIN,
            semilla=3,
            volumen=datos_prueba.Volumen(
                estudiantes_iniciales=600, nuevos_por_periodo=0, historicos=0
            ),
        )
        corte = db.session.scalar(
            select(Corte)
            .join(Alerta, Alerta.corte_id == Corte.id)
            .group_by(Corte.id)
            .order_by(func.count(Alerta.id).desc())
            .limit(1)
        )
        total = db.session.scalar(
            select(func.count(Alerta.id)).where(Alerta.corte_id == corte.id)
        )
        assert total >= 1900
        inicio = time.perf_counter()
        for filtros in (
            alertas.FiltrosAlertas(),
            alertas.FiltrosAlertas(tipo="roja"),
            alertas.FiltrosAlertas(motivo="ambos"),
            alertas.FiltrosAlertas(solo_riesgo_alto=True),
        ):
            alertas.listar_alertas(corte, filtros, pagina=2)
        alertas.resumen_corte(corte)
        assert (time.perf_counter() - inicio) / 4 < 2.0
