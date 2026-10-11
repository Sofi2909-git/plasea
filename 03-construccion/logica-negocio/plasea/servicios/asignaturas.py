"""Asignaturas (RF-13). "Asignatura" y "materia" son el mismo concepto."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from flask_sqlalchemy.pagination import Pagination
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from plasea.modelos import Asignatura, Curso, ProgramaAcademico, db
from plasea.servicios import bitacora
from plasea.servicios.comunes import ErrorNegocio

CREDITOS_VALIDOS = (3, 4)
NIVEL_MINIMO, NIVEL_MAXIMO = 1, 10
HORAS_SEMANALES_MAXIMAS = 20
ASIGNATURAS_POR_PAGINA = 25
_PATRON_CODIGO = re.compile(r"^[A-Z0-9-]{2,20}$")


@dataclass(frozen=True)
class DatosAsignatura:
    """Datos editables de una asignatura."""

    codigo: str
    nombre: str
    programa_academico_id: int
    creditos: int
    horas_semanales: int
    nivel: int


def listar_programas() -> list[ProgramaAcademico]:
    """Programas académicos disponibles (hoy solo Ingeniería de Sistemas)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-13
    return list(
        db.session.scalars(select(ProgramaAcademico).order_by(ProgramaAcademico.nombre))
    )


def listar_asignaturas(
    texto: Optional[str] = None, nivel: Optional[int] = None, pagina: int = 1
) -> Pagination:
    """Lista asignaturas con búsqueda por código o nombre y filtro por nivel."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-13
    consulta = select(Asignatura).options(joinedload(Asignatura.programa_academico))
    texto_limpio = (texto or "").strip()[:150]
    if texto_limpio:
        consulta = consulta.where(
            or_(
                Asignatura.codigo.contains(texto_limpio, autoescape=True),
                Asignatura.nombre.contains(texto_limpio, autoescape=True),
            )
        )
    if nivel is not None and NIVEL_MINIMO <= nivel <= NIVEL_MAXIMO:
        consulta = consulta.where(Asignatura.nivel == nivel)
    consulta = consulta.order_by(Asignatura.nivel, Asignatura.codigo)
    return db.paginate(
        consulta, page=max(pagina, 1), per_page=ASIGNATURAS_POR_PAGINA, error_out=False
    )


def todas_las_asignaturas() -> list[Asignatura]:
    """Todas las asignaturas ordenadas por código (para selectores)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-13
    return list(db.session.scalars(select(Asignatura).order_by(Asignatura.codigo)))


def obtener_asignatura(asignatura_id: int) -> Asignatura:
    """Devuelve la asignatura o lanza ``ErrorNegocio`` si no existe."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-13
    asignatura = db.session.get(Asignatura, asignatura_id)
    if asignatura is None:
        raise ErrorNegocio("La asignatura solicitada no existe.")
    return asignatura


def contar_cursos(asignatura_id: int) -> int:
    """Número de cursos (de cualquier período) que tiene la asignatura."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-13
    return db.session.scalar(
        select(func.count(Curso.id)).where(Curso.asignatura_id == asignatura_id)
    )


def _normalizar(
    datos: DatosAsignatura, excluir_id: Optional[int] = None
) -> DatosAsignatura:
    """Valida en el servidor las reglas de RF-13."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-13
    codigo = datos.codigo.strip().upper()
    nombre = " ".join(datos.nombre.split())
    if not _PATRON_CODIGO.match(codigo):
        raise ErrorNegocio(
            "El código debe tener de 2 a 20 caracteres: letras, números o guion."
        )
    if not 3 <= len(nombre) <= 150:
        raise ErrorNegocio("El nombre debe tener entre 3 y 150 caracteres.")
    if datos.creditos not in CREDITOS_VALIDOS:
        raise ErrorNegocio("Los créditos solo pueden ser 3 o 4.")
    if not 1 <= datos.horas_semanales <= HORAS_SEMANALES_MAXIMAS:
        raise ErrorNegocio(
            f"Las horas semanales deben estar entre 1 y {HORAS_SEMANALES_MAXIMAS}."
        )
    if not NIVEL_MINIMO <= datos.nivel <= NIVEL_MAXIMO:
        raise ErrorNegocio("El nivel de la carrera debe estar entre 1 y 10.")
    if db.session.get(ProgramaAcademico, datos.programa_academico_id) is None:
        raise ErrorNegocio("Seleccione un programa académico válido.")
    consulta = select(Asignatura.id).where(Asignatura.codigo == codigo)
    if excluir_id is not None:
        consulta = consulta.where(Asignatura.id != excluir_id)
    if db.session.scalar(consulta) is not None:
        raise ErrorNegocio(f"Ya existe una asignatura con el código {codigo}.")
    return DatosAsignatura(
        codigo,
        nombre,
        datos.programa_academico_id,
        datos.creditos,
        datos.horas_semanales,
        datos.nivel,
    )


def crear_asignatura(datos: DatosAsignatura, actor_id: int) -> Asignatura:
    """Registra una asignatura (RF-13)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-13
    try:
        datos = _normalizar(datos)
        asignatura = Asignatura(**datos.__dict__)
        db.session.add(asignatura)
        db.session.flush()
        bitacora.registrar_evento(
            bitacora.EVENTO_CAMBIO_ADMINISTRATIVO,
            usuario_id=actor_id,
            entidad="asignaturas",
            entidad_id=asignatura.id,
            detalle=f"Registro de la asignatura {asignatura.codigo}",
        )
        db.session.commit()
        return asignatura
    except Exception:
        db.session.rollback()
        raise


def modificar_asignatura(
    asignatura_id: int, datos: DatosAsignatura, actor_id: int
) -> Asignatura:
    """Modifica una asignatura (RF-13)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-13
    try:
        asignatura = obtener_asignatura(asignatura_id)
        datos = _normalizar(datos, excluir_id=asignatura.id)
        for campo, valor in datos.__dict__.items():
            setattr(asignatura, campo, valor)
        bitacora.registrar_evento(
            bitacora.EVENTO_CAMBIO_ADMINISTRATIVO,
            usuario_id=actor_id,
            entidad="asignaturas",
            entidad_id=asignatura.id,
            detalle=f"Modificación de la asignatura {asignatura.codigo}",
        )
        db.session.commit()
        return asignatura
    except Exception:
        db.session.rollback()
        raise


def eliminar_asignatura(asignatura_id: int, actor_id: int) -> str:
    """Elimina una asignatura sin cursos; con cursos no se elimina (RF-13).

    Returns:
        El código de la asignatura eliminada.
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-13
    try:
        asignatura = obtener_asignatura(asignatura_id)
        if contar_cursos(asignatura.id):
            raise ErrorNegocio(
                "La asignatura tiene cursos registrados y no se puede eliminar."
            )
        codigo = asignatura.codigo
        db.session.delete(asignatura)
        bitacora.registrar_evento(
            bitacora.EVENTO_CAMBIO_ADMINISTRATIVO,
            usuario_id=actor_id,
            entidad="asignaturas",
            entidad_id=asignatura_id,
            detalle=f"Eliminación de la asignatura {codigo} (sin cursos)",
        )
        db.session.commit()
        return codigo
    except Exception:
        db.session.rollback()
        raise
