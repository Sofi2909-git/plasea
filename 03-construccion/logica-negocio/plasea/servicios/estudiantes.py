"""Estudiantes (RF-21) y su historial de estados (RF-22).

Los estudiantes nunca se eliminan: su situación se maneja con el historial de
estados. El estado vigente en una fecha es el de fecha efectiva más reciente que
no sea posterior a esa fecha.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Optional

from flask_sqlalchemy.pagination import Pagination
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from plasea.modelos import (
    EstadoEstudiante,
    Estudiante,
    HistorialEstadoEstudiante,
    ProgramaAcademico,
    db,
)
from plasea.servicios import bitacora
from plasea.servicios.comunes import ErrorNegocio, ahora

ESTADO_ACTIVO = "activo"
ESTADOS_TERMINALES = ("graduado", "retirado_formal", "cancelado")
ESTUDIANTES_POR_PAGINA = 25
_PATRON_CODIGO = re.compile(r"^[A-Za-z0-9-]{3,20}$")
_PATRON_COHORTE = re.compile(r"^\d{4}-[12]$")
_PATRON_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class DatosEstudiante:
    """Datos editables de un estudiante (RF-21)."""

    codigo: str
    nombres: str
    correo: str
    programa_academico_id: int
    periodo_ingreso: str


def hoy() -> dt.date:
    """Fecha actual de Colombia."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-22
    return ahora().date()


def listar_estados() -> list[EstadoEstudiante]:
    """Catálogo de estados del estudiante."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-22
    return list(
        db.session.scalars(select(EstadoEstudiante).order_by(EstadoEstudiante.id))
    )


def _subconsulta_estado_vigente(fecha: dt.date):
    """Subconsulta con el estado vigente de cada estudiante en ``fecha``.

    Usa ROW_NUMBER() por estudiante (función de ventana estándar, soportada por
    MariaDB 10.2 o superior) sobre el índice (estudiante_id, fecha_efectiva).
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-22
    numerado = (
        select(
            HistorialEstadoEstudiante.estudiante_id,
            HistorialEstadoEstudiante.estado_estudiante_id,
            HistorialEstadoEstudiante.fecha_efectiva,
            func.row_number()
            .over(
                partition_by=HistorialEstadoEstudiante.estudiante_id,
                order_by=(
                    HistorialEstadoEstudiante.fecha_efectiva.desc(),
                    HistorialEstadoEstudiante.id.desc(),
                ),
            )
            .label("orden"),
        )
        .where(HistorialEstadoEstudiante.fecha_efectiva <= fecha)
        .subquery()
    )
    return (
        select(
            numerado.c.estudiante_id,
            numerado.c.fecha_efectiva,
            EstadoEstudiante.codigo,
            EstadoEstudiante.nombre,
        )
        .join(EstadoEstudiante, EstadoEstudiante.id == numerado.c.estado_estudiante_id)
        .where(numerado.c.orden == 1)
        .subquery()
    )


def listar_estudiantes(
    texto: Optional[str] = None,
    cohorte: Optional[str] = None,
    estado: Optional[str] = None,
    pagina: int = 1,
) -> Pagination:
    """Lista estudiantes con su estado vigente hoy (RF-21, RF-22).

    Cada elemento es una fila (estudiante, código de estado, nombre de estado).
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-21
    vigente = _subconsulta_estado_vigente(hoy())
    consulta = select(Estudiante).outerjoin(
        vigente, vigente.c.estudiante_id == Estudiante.id
    )
    texto_limpio = (texto or "").strip()[:150]
    if texto_limpio:
        consulta = consulta.where(
            or_(
                Estudiante.codigo.contains(texto_limpio, autoescape=True),
                Estudiante.nombres.contains(texto_limpio, autoescape=True),
                Estudiante.correo.contains(texto_limpio, autoescape=True),
            )
        )
    if cohorte and _PATRON_COHORTE.match(cohorte):
        consulta = consulta.where(Estudiante.periodo_ingreso == cohorte)
    if estado == "sin_estado":
        consulta = consulta.where(vigente.c.codigo.is_(None))
    elif estado:
        consulta = consulta.where(vigente.c.codigo == estado)
    consulta = consulta.order_by(Estudiante.nombres, Estudiante.id)
    paginacion = db.paginate(
        consulta,
        page=max(pagina, 1),
        per_page=ESTUDIANTES_POR_PAGINA,
        error_out=False,
    )
    # Una sola consulta adicional trae el estado de los estudiantes de la página
    # (evita N+1; Flask-SQLAlchemy 3.1 pagina solo entidades).
    ids = [estudiante.id for estudiante in paginacion.items]
    estados: dict[int, tuple[str, str]] = {}
    if ids:
        filas = db.session.execute(
            select(vigente.c.estudiante_id, vigente.c.codigo, vigente.c.nombre).where(
                vigente.c.estudiante_id.in_(ids)
            )
        )
        estados = {fila[0]: (fila[1], fila[2]) for fila in filas}
    paginacion.items = [
        (estudiante, *estados.get(estudiante.id, (None, None)))
        for estudiante in paginacion.items
    ]
    return paginacion


def listar_cohortes() -> list[str]:
    """Períodos de ingreso existentes, del más reciente al más antiguo."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-21
    return list(
        db.session.scalars(
            select(Estudiante.periodo_ingreso)
            .distinct()
            .order_by(Estudiante.periodo_ingreso.desc())
        )
    )


def obtener_estudiante(estudiante_id: int) -> Estudiante:
    """Devuelve el estudiante o lanza ``ErrorNegocio`` si no existe."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-21
    estudiante = db.session.get(Estudiante, estudiante_id)
    if estudiante is None:
        raise ErrorNegocio("El estudiante solicitado no existe.")
    return estudiante


def buscar_por_codigo(codigo: str) -> Optional[Estudiante]:
    """Busca un estudiante por su código estudiantil."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-21
    return db.session.scalar(
        select(Estudiante).where(Estudiante.codigo == (codigo or "").strip())
    )


def estado_en_fecha(
    estudiante_id: int, fecha: dt.date
) -> Optional[HistorialEstadoEstudiante]:
    """Registro de estado vigente del estudiante en una fecha (RF-22)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-22
    return db.session.scalar(
        select(HistorialEstadoEstudiante)
        .where(
            HistorialEstadoEstudiante.estudiante_id == estudiante_id,
            HistorialEstadoEstudiante.fecha_efectiva <= fecha,
        )
        .order_by(
            HistorialEstadoEstudiante.fecha_efectiva.desc(),
            HistorialEstadoEstudiante.id.desc(),
        )
        .limit(1)
    )


def _normalizar(
    datos: DatosEstudiante, excluir_id: Optional[int] = None
) -> DatosEstudiante:
    """Valida en el servidor los datos de RF-21."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-21
    codigo, nombres, correo, cohorte = normalizar_formato(
        datos.codigo, datos.nombres, datos.correo, datos.periodo_ingreso
    )
    if db.session.get(ProgramaAcademico, datos.programa_academico_id) is None:
        raise ErrorNegocio("Seleccione un programa académico válido.")
    consulta = select(Estudiante.id).where(Estudiante.codigo == codigo)
    if excluir_id is not None:
        consulta = consulta.where(Estudiante.id != excluir_id)
    if db.session.scalar(consulta) is not None:
        raise ErrorNegocio(f"Ya existe un estudiante con el código {codigo}.")
    return DatosEstudiante(
        codigo, nombres, correo, datos.programa_academico_id, cohorte
    )


def normalizar_formato(
    codigo: str, nombres: str, correo: str, cohorte: str
) -> tuple[str, str, str, str]:
    """Normaliza y valida el formato de los datos de un estudiante, sin consultar
    la base de datos (RF-21; la usa también la carga por CSV de RF-24).

    Raises:
        ErrorNegocio: con el primer dato inválido.
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-21
    codigo = (codigo or "").strip()
    nombres = " ".join((nombres or "").split())
    correo = (correo or "").strip().lower()
    cohorte = (cohorte or "").strip()
    if not _PATRON_CODIGO.match(codigo):
        raise ErrorNegocio(
            "El código debe tener de 3 a 20 caracteres: letras, números o guion."
        )
    if not 3 <= len(nombres) <= 150:
        raise ErrorNegocio("Los nombres deben tener entre 3 y 150 caracteres.")
    if len(correo) > 254 or not _PATRON_CORREO.match(correo):
        raise ErrorNegocio("Escriba un correo electrónico válido.")
    if not _PATRON_COHORTE.match(cohorte):
        raise ErrorNegocio("El período de ingreso debe tener la forma AAAA-1 o AAAA-2.")
    return codigo, nombres, correo, cohorte


def _estado_por_codigo(codigo: str) -> EstadoEstudiante:
    """Devuelve el estado del catálogo con ese código."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-22
    estado = db.session.scalar(
        select(EstadoEstudiante).where(EstadoEstudiante.codigo == codigo)
    )
    if estado is None:
        raise ErrorNegocio("Seleccione un estado válido.")
    return estado


def crear_estudiante(
    datos: DatosEstudiante, fecha_estado_inicial: dt.date, actor_id: int
) -> Estudiante:
    """Registra un estudiante con estado inicial "activo" (RF-21, RF-22)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-21
    try:
        datos = _normalizar(datos)
        estudiante = Estudiante(**datos.__dict__)
        db.session.add(estudiante)
        db.session.flush()
        db.session.add(
            HistorialEstadoEstudiante(
                estudiante_id=estudiante.id,
                estado_estudiante_id=_estado_por_codigo(ESTADO_ACTIVO).id,
                fecha_efectiva=fecha_estado_inicial,
                registrado_por_usuario_id=actor_id,
            )
        )
        bitacora.registrar_evento(
            bitacora.EVENTO_CAMBIO_ADMINISTRATIVO,
            usuario_id=actor_id,
            entidad="estudiantes",
            entidad_id=estudiante.id,
            detalle="Registro de estudiante con estado inicial activo",
        )
        db.session.commit()
        return estudiante
    except Exception:
        db.session.rollback()
        raise


def modificar_estudiante(
    estudiante_id: int, datos: DatosEstudiante, actor_id: int
) -> Estudiante:
    """Modifica los datos de un estudiante (RF-21)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-21
    try:
        estudiante = obtener_estudiante(estudiante_id)
        datos = _normalizar(datos, excluir_id=estudiante.id)
        cambios = [
            campo
            for campo, valor in datos.__dict__.items()
            if getattr(estudiante, campo) != valor
        ]
        for campo in cambios:
            setattr(estudiante, campo, getattr(datos, campo))
        if cambios:
            bitacora.registrar_evento(
                bitacora.EVENTO_CAMBIO_ADMINISTRATIVO,
                usuario_id=actor_id,
                entidad="estudiantes",
                entidad_id=estudiante.id,
                detalle="Modificación de " + ", ".join(cambios),
            )
        db.session.commit()
        return estudiante
    except Exception:
        db.session.rollback()
        raise


def registrar_estado(
    estudiante_id: int, codigo_estado: str, fecha_efectiva: dt.date, actor_id: int
) -> HistorialEstadoEstudiante:
    """Agrega un estado con su fecha efectiva al historial del estudiante (RF-22).

    El historial no se modifica ni se elimina: un error se corrige registrando
    un estado nuevo.
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-22
    try:
        estudiante = obtener_estudiante(estudiante_id)
        estado = _estado_por_codigo(codigo_estado)
        if fecha_efectiva > hoy() + dt.timedelta(days=366):
            raise ErrorNegocio(
                "La fecha efectiva no puede superar un año en el futuro."
            )
        registro = HistorialEstadoEstudiante(
            estudiante_id=estudiante.id,
            estado_estudiante_id=estado.id,
            fecha_efectiva=fecha_efectiva,
            registrado_por_usuario_id=actor_id,
        )
        db.session.add(registro)
        db.session.flush()
        bitacora.registrar_evento(
            bitacora.EVENTO_CAMBIO_ADMINISTRATIVO,
            usuario_id=actor_id,
            entidad="estudiantes",
            entidad_id=estudiante.id,
            detalle=f"Estado {estado.codigo} desde {fecha_efectiva:%d/%m/%Y}",
        )
        db.session.commit()
        return registro
    except Exception:
        db.session.rollback()
        raise


def historial_estados(estudiante_id: int) -> list[HistorialEstadoEstudiante]:
    """Historial de estados del más reciente al más antiguo (RF-22)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-22
    return list(
        db.session.scalars(
            select(HistorialEstadoEstudiante)
            .options(
                joinedload(HistorialEstadoEstudiante.estado_estudiante),
                joinedload(HistorialEstadoEstudiante.registrado_por),
            )
            .where(HistorialEstadoEstudiante.estudiante_id == estudiante_id)
            .order_by(
                HistorialEstadoEstudiante.fecha_efectiva.desc(),
                HistorialEstadoEstudiante.id.desc(),
            )
        )
    )


def subconsulta_estado_vigente(fecha: dt.date):
    """Estado vigente de cada estudiante en ``fecha`` (uso desde otros módulos).

    La usa la continuidad (RF-49) para excluir graduados y aplazados.
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-22
    return _subconsulta_estado_vigente(fecha)
