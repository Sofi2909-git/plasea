"""Exportaciones a CSV (RF-58, RF-59).

Formato: separador punto y coma, UTF-8 con BOM (Excel en Windows lo abre con
tildes) y coma decimal. Todo texto que empiece con =, +, -, @, tabulador o
retorno de carro se antepone con un apóstrofo para que la hoja de cálculo no
lo ejecute como fórmula. Se exportan todas las filas del filtro, no solo la
página visible. Cada exportación queda en la bitácora (RF-61).
"""

from __future__ import annotations

import csv
import io
from decimal import Decimal
from typing import Any, Iterable, Optional

from sqlalchemy import select

from plasea.modelos import Corte, Curso, Usuario, db
from plasea.servicios import alertas, analitica, bitacora, calculos

EVENTO_EXPORTACION = "exportacion"
_INICIOS_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def neutralizar(valor: Any) -> str:
    """Convierte a texto y neutraliza fórmulas (CSV injection)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-58
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "Sí" if valor else "No"
    if isinstance(valor, Decimal):
        return format(valor, "f").replace(".", ",")
    texto = str(valor)
    if texto.startswith(_INICIOS_FORMULA):
        return "'" + texto
    return texto


def generar_csv(encabezado: list[str], filas: Iterable[Iterable[Any]]) -> bytes:
    """CSV con BOM y punto y coma, con todos los valores neutralizados."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-58
    salida = io.StringIO()
    escritor = csv.writer(salida, delimiter=";", lineterminator="\r\n")
    escritor.writerow(encabezado)
    for fila in filas:
        escritor.writerow([neutralizar(valor) for valor in fila])
    return ("﻿" + salida.getvalue()).encode("utf-8")


def _registrar(actor_id: int, detalle: str) -> None:
    """Deja la exportación en la bitácora y confirma."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-58
    bitacora.registrar_evento(
        EVENTO_EXPORTACION,
        usuario_id=actor_id,
        entidad="exportaciones",
        detalle=detalle,
    )
    db.session.commit()


def csv_alertas(
    corte: Corte, filtros: alertas.FiltrosAlertas, actor_id: int
) -> tuple[str, bytes, int]:
    """Lista de alertas con los filtros aplicados, todas las filas (RF-58).

    Returns:
        (nombre del archivo, contenido, número de filas).
    """
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-58
    profesores = dict(
        db.session.execute(
            select(Usuario.id, Usuario.nombre_completo).where(
                Usuario.id.in_(
                    select(Curso.profesor_usuario_id).where(
                        Curso.periodo_academico_id == corte.periodo_academico_id
                    )
                )
            )
        ).all()
    )
    en_riesgo = analitica.estudiantes_en_riesgo(corte.id)
    definitiva = corte.cerrado_en is not None
    identificador = corte.periodo_academico.identificador
    filas = []
    for alerta in db.session.scalars(alertas.consulta_alertas(corte, filtros)):
        estudiante = alerta.inscripcion.matricula_periodo.estudiante
        curso = alerta.inscripcion.curso
        motivo = (
            "Nota e inasistencia"
            if alerta.motivo_nota and alerta.motivo_inasistencia
            else ("Nota" if alerta.motivo_nota else "Inasistencia")
        )
        filas.append(
            [
                estudiante.codigo,
                estudiante.nombres,
                estudiante.correo,
                curso.asignatura.codigo,
                curso.asignatura.nombre,
                curso.codigo,
                profesores.get(curso.profesor_usuario_id, ""),
                identificador,
                corte.numero,
                "Roja" if alerta.estado_alerta == calculos.ESTADO_ROJA else "Amarilla",
                motivo,
                alerta.nota_corte,
                alerta.nota_acumulada,
                alerta.nota_requerida,
                alerta.porcentaje_inasistencia,
                alerta.porcentaje_ritmo,
                alerta.horas_ausentes,
                estudiante.id in en_riesgo,
                "Definitiva" if definitiva else "Provisional",
            ]
        )
    contenido = generar_csv(
        [
            "Código",
            "Estudiante",
            "Correo",
            "Asignatura",
            "Nombre asignatura",
            "Curso",
            "Profesor",
            "Período",
            "Corte",
            "Tipo",
            "Motivo",
            "Nota corte",
            "Nota acumulada",
            "Nota requerida",
            "% inasistencia",
            "% ritmo",
            "Horas ausentes",
            "Riesgo alto",
            "Estado",
        ],
        filas,
    )
    _registrar(
        actor_id,
        f"Exportación CSV de alertas {identificador} corte {corte.numero}: "
        f"{len(filas)} filas",
    )
    return f"alertas_{identificador}_corte{corte.numero}.csv", contenido, len(filas)


def csv_resultados(
    corte: Corte, filtros: analitica.FiltrosResultados, actor_id: int
) -> tuple[str, bytes, int]:
    """Resultados por asignatura y curso con los filtros de RF-48 (RF-59)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-59
    filas, total = analitica.resultados(corte, filtros)

    def porcentaje(fila: analitica.FilaResultado, valor: int) -> Optional[Decimal]:
        # Responsable: Wilson D'Alessandro Saavedra Rolón
        # RF-59
        return calculos.redondear(fila.porcentaje(valor), 1)

    datos = [
        [
            f.asignatura,
            f.nombre_asignatura,
            f.curso,
            f.profesor,
            f.inscritos,
            f.aprobados,
            porcentaje(f, f.aprobados),
            f.en_alerta,
            porcentaje(f, f.en_alerta),
            f.perdidos,
            porcentaje(f, f.perdidos),
        ]
        for f in [*filas, total]
    ]
    identificador = corte.periodo_academico.identificador
    contenido = generar_csv(
        [
            "Asignatura",
            "Nombre asignatura",
            "Curso",
            "Profesor",
            "Inscritos",
            "Aprobados",
            "% aprobados",
            "En alerta",
            "% en alerta",
            "Perdidos",
            "% perdidos",
        ],
        datos,
    )
    _registrar(
        actor_id,
        f"Exportación CSV de resultados {identificador} corte {corte.numero}: "
        f"{len(filas)} cursos",
    )
    return f"resultados_{identificador}_corte{corte.numero}.csv", contenido, len(filas)


def registrar_vista_imprimible(estudiante_codigo: str, actor_id: int) -> None:
    """Deja en la bitácora la generación de la vista imprimible (RF-60)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-60
    _registrar(actor_id, f"Vista imprimible del histórico de {estudiante_codigo}")
