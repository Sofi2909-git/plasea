"""Cursos de una asignatura en un período (RF-14) y su horario semanal (RF-15)."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload, selectinload

from plasea.modelos import (
    Asignatura,
    BloqueHorario,
    Curso,
    Inscripcion,
    PeriodoAcademico,
    Rol,
    SesionClase,
    Usuario,
    db,
)
from plasea.servicios import bitacora, calendario
from plasea.servicios.comunes import ErrorNegocio

ROL_PROFESOR = "profesor"
ESTADOS_ASIGNABLES = ("activa", "pendiente_activacion")
DURACIONES_VALIDAS_HORAS = (1, 2, 3)
DIAS_SEMANA = {
    1: "Lunes",
    2: "Martes",
    3: "Miércoles",
    4: "Jueves",
    5: "Viernes",
    6: "Sábado",
    7: "Domingo",
}
_PATRON_CODIGO = re.compile(r"^[A-Z0-9-]{1,10}$")


@dataclass(frozen=True)
class DatosCurso:
    """Datos de un curso (RF-14)."""

    asignatura_id: int
    periodo_academico_id: int
    codigo: str
    profesor_usuario_id: int


@dataclass(frozen=True)
class FilaCurso:
    """Curso con sus totales para el listado."""

    curso: Curso
    inscritos: int
    horas_totales: int


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------


def profesores_asignables() -> list[Usuario]:
    """Usuarios con rol Profesor activos o pendientes de activación (RF-08, RF-14)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-14
    return list(
        db.session.scalars(
            select(Usuario)
            .join(Usuario.rol)
            .where(
                Rol.codigo == ROL_PROFESOR,
                Usuario.estado_cuenta.in_(ESTADOS_ASIGNABLES),
            )
            .order_by(Usuario.nombre_completo)
        )
    )


def listar_cursos(
    periodo_id: Optional[int] = None,
    asignatura_id: Optional[int] = None,
    profesor_id: Optional[int] = None,
) -> list[FilaCurso]:
    """Lista cursos con número de inscritos vigentes y horas totales calculadas.

    Los totales salen de dos subconsultas agregadas para evitar una consulta
    por curso.
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-14
    inscritos = (
        select(Inscripcion.curso_id, func.count(Inscripcion.id).label("total"))
        .where(Inscripcion.retirada_en.is_(None))
        .group_by(Inscripcion.curso_id)
        .subquery()
    )
    horas = (
        select(
            SesionClase.curso_id,
            func.sum(SesionClase.duracion_horas).label("total"),
        )
        .group_by(SesionClase.curso_id)
        .subquery()
    )
    consulta = (
        select(
            Curso,
            func.coalesce(inscritos.c.total, 0),
            func.coalesce(horas.c.total, 0),
        )
        .join(Asignatura, Asignatura.id == Curso.asignatura_id)
        .outerjoin(inscritos, inscritos.c.curso_id == Curso.id)
        .outerjoin(horas, horas.c.curso_id == Curso.id)
        .options(
            joinedload(Curso.asignatura),
            joinedload(Curso.profesor),
            joinedload(Curso.periodo_academico),
            selectinload(Curso.bloques_horario),
        )
        .order_by(Asignatura.codigo, Curso.codigo)
    )
    if periodo_id is not None:
        consulta = consulta.where(Curso.periodo_academico_id == periodo_id)
    if asignatura_id is not None:
        consulta = consulta.where(Curso.asignatura_id == asignatura_id)
    if profesor_id is not None:
        consulta = consulta.where(Curso.profesor_usuario_id == profesor_id)
    return [
        FilaCurso(curso, int(total_inscritos), int(total_horas))
        for curso, total_inscritos, total_horas in db.session.execute(consulta)
    ]


def obtener_curso(curso_id: int) -> Curso:
    """Devuelve el curso o lanza ``ErrorNegocio`` si no existe."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-14
    curso = db.session.get(Curso, curso_id)
    if curso is None:
        raise ErrorNegocio("El curso solicitado no existe.")
    return curso


# ---------------------------------------------------------------------------
# RF-14: cursos
# ---------------------------------------------------------------------------


def _validar_profesor(profesor_id: int) -> Usuario:
    """El docente debe ser una cuenta con rol Profesor activa o pendiente."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-14
    profesor = db.session.get(Usuario, profesor_id)
    if (
        profesor is None
        or profesor.rol.codigo != ROL_PROFESOR
        or profesor.estado_cuenta not in ESTADOS_ASIGNABLES
    ):
        raise ErrorNegocio(
            "Seleccione un docente con rol Profesor y cuenta habilitada."
        )
    return profesor


def _validar_codigo(
    codigo: str, asignatura_id: int, periodo_id: int, excluir_id: Optional[int] = None
) -> str:
    """El código del curso es único por asignatura y período."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-14
    codigo = codigo.strip().upper()
    if not _PATRON_CODIGO.match(codigo):
        raise ErrorNegocio(
            "El código del curso admite hasta 10 letras, números o guion (ej.: T01)."
        )
    consulta = select(Curso.id).where(
        Curso.asignatura_id == asignatura_id,
        Curso.periodo_academico_id == periodo_id,
        Curso.codigo == codigo,
    )
    if excluir_id is not None:
        consulta = consulta.where(Curso.id != excluir_id)
    if db.session.scalar(consulta) is not None:
        raise ErrorNegocio(
            f"Ya existe el curso {codigo} de esa asignatura en ese período."
        )
    return codigo


def crear_curso(datos: DatosCurso, actor_id: int) -> Curso:
    """Registra un curso de una asignatura en un período con su docente (RF-14)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-14
    try:
        if db.session.get(Asignatura, datos.asignatura_id) is None:
            raise ErrorNegocio("Seleccione una asignatura válida.")
        periodo = db.session.get(PeriodoAcademico, datos.periodo_academico_id)
        if periodo is None:
            raise ErrorNegocio("Seleccione un período válido.")
        codigo = _validar_codigo(
            datos.codigo, datos.asignatura_id, datos.periodo_academico_id
        )
        _validar_profesor(datos.profesor_usuario_id)
        curso = Curso(
            asignatura_id=datos.asignatura_id,
            periodo_academico_id=datos.periodo_academico_id,
            codigo=codigo,
            profesor_usuario_id=datos.profesor_usuario_id,
        )
        db.session.add(curso)
        db.session.flush()
        bitacora.registrar_evento(
            bitacora.EVENTO_CAMBIO_ADMINISTRATIVO,
            usuario_id=actor_id,
            entidad="cursos",
            entidad_id=curso.id,
            detalle=f"Registro del curso {codigo} en el período "
            f"{periodo.identificador}",
        )
        db.session.commit()
        return curso
    except Exception:
        db.session.rollback()
        raise


def modificar_curso(
    curso_id: int, codigo: str, profesor_id: int, actor_id: int
) -> Curso:
    """Modifica el código y el docente de un curso (RF-14).

    La asignatura y el período no cambian: definen a qué pertenecen las
    inscripciones y el calendario del curso.
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-14
    try:
        curso = obtener_curso(curso_id)
        nuevo_codigo = _validar_codigo(
            codigo, curso.asignatura_id, curso.periodo_academico_id, excluir_id=curso.id
        )
        _validar_profesor(profesor_id)
        cambios = []
        if curso.codigo != nuevo_codigo:
            cambios.append("código")
            curso.codigo = nuevo_codigo
        if curso.profesor_usuario_id != profesor_id:
            cambios.append("docente")
            curso.profesor_usuario_id = profesor_id
        if cambios:
            bitacora.registrar_evento(
                bitacora.EVENTO_CAMBIO_ADMINISTRATIVO,
                usuario_id=actor_id,
                entidad="cursos",
                entidad_id=curso.id,
                detalle="Modificación de " + " y ".join(cambios) + " del curso",
            )
        db.session.commit()
        db.session.refresh(curso)
        return curso
    except Exception:
        db.session.rollback()
        raise


# ---------------------------------------------------------------------------
# RF-15: horario semanal
# ---------------------------------------------------------------------------


def _minutos(hora: dt.time) -> int:
    """Minutos transcurridos desde la medianoche."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-15
    return hora.hour * 60 + hora.minute


def horas_semanales_programadas(curso: Curso) -> int:
    """Suma de las horas de los bloques del curso."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-15
    return sum(
        (_minutos(b.hora_fin) - _minutos(b.hora_inicio)) // 60
        for b in curso.bloques_horario
    )


def advertencia_horas(curso: Curso) -> Optional[str]:
    """Advierte si el horario difiere de las horas semanales de la asignatura."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-15
    programadas = horas_semanales_programadas(curso)
    esperadas = curso.asignatura.horas_semanales
    if programadas == esperadas:
        return None
    return (
        f"El horario suma {programadas} h por semana y la asignatura tiene "
        f"{esperadas} h semanales."
    )


def validar_bloque(
    dia_semana: int,
    hora_inicio: dt.time,
    hora_fin: dt.time,
    otros_bloques: list[tuple[int, dt.time, dt.time]],
) -> None:
    """Aplica las reglas de RF-15 a un bloque nuevo.

    Raises:
        ErrorNegocio: día inválido, duración distinta de 1, 2 o 3 horas o
            solapamiento con otro bloque del mismo curso.
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-15
    if dia_semana not in DIAS_SEMANA:
        raise ErrorNegocio("Seleccione un día de la semana válido.")
    duracion = _minutos(hora_fin) - _minutos(hora_inicio)
    if duracion <= 0:
        raise ErrorNegocio("La hora de fin debe ser posterior a la de inicio.")
    if duracion % 60 or duracion // 60 not in DURACIONES_VALIDAS_HORAS:
        raise ErrorNegocio("Cada bloque debe durar exactamente 1, 2 o 3 horas.")
    for dia, inicio, fin in otros_bloques:
        if (
            dia == dia_semana
            and _minutos(hora_inicio) < _minutos(fin)
            and _minutos(inicio) < _minutos(hora_fin)
        ):
            raise ErrorNegocio(
                f"El bloque se solapa con el de {DIAS_SEMANA[dia]} "
                f"{inicio:%H:%M}-{fin:%H:%M}."
            )


def _verificar_horario_editable(curso: Curso) -> None:
    """El horario no cambia si el curso ya tiene asistencia (RF-19)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-15
    if calendario.curso_tiene_asistencia(curso.id):
        raise ErrorNegocio(
            "El curso ya tiene asistencia registrada; su horario no se puede cambiar."
        )


def agregar_bloque(
    curso_id: int,
    dia_semana: int,
    hora_inicio: dt.time,
    hora_fin: dt.time,
    actor_id: int,
) -> Curso:
    """Agrega un bloque al horario y regenera el calendario del curso (RF-15, RF-19)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-15
    try:
        curso = obtener_curso(curso_id)
        _verificar_horario_editable(curso)
        otros = [
            (b.dia_semana, b.hora_inicio, b.hora_fin) for b in curso.bloques_horario
        ]
        validar_bloque(dia_semana, hora_inicio, hora_fin, otros)
        db.session.add(
            BloqueHorario(
                curso_id=curso.id,
                dia_semana=dia_semana,
                hora_inicio=hora_inicio,
                hora_fin=hora_fin,
            )
        )
        db.session.flush()
        calendario.regenerar_calendario(curso)
        bitacora.registrar_evento(
            bitacora.EVENTO_CAMBIO_ADMINISTRATIVO,
            usuario_id=actor_id,
            entidad="cursos",
            entidad_id=curso.id,
            detalle=(
                f"Bloque agregado: {DIAS_SEMANA[dia_semana]} "
                f"{hora_inicio:%H:%M}-{hora_fin:%H:%M}"
            ),
        )
        db.session.commit()
        db.session.refresh(curso)
        return curso
    except Exception:
        db.session.rollback()
        raise


def eliminar_bloque(bloque_id: int, actor_id: int) -> Curso:
    """Quita un bloque del horario y regenera el calendario del curso (RF-15, RF-19)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-15
    try:
        bloque = db.session.get(BloqueHorario, bloque_id)
        if bloque is None:
            raise ErrorNegocio("El bloque de horario no existe.")
        curso = bloque.curso
        _verificar_horario_editable(curso)
        descripcion = (
            f"{DIAS_SEMANA[bloque.dia_semana]} "
            f"{bloque.hora_inicio:%H:%M}-{bloque.hora_fin:%H:%M}"
        )
        db.session.delete(bloque)
        db.session.flush()
        db.session.expire(curso, ["bloques_horario"])
        calendario.regenerar_calendario(curso)
        bitacora.registrar_evento(
            bitacora.EVENTO_CAMBIO_ADMINISTRATIVO,
            usuario_id=actor_id,
            entidad="cursos",
            entidad_id=curso.id,
            detalle=f"Bloque retirado: {descripcion}",
        )
        db.session.commit()
        db.session.refresh(curso)
        return curso
    except Exception:
        db.session.rollback()
        raise


def generar_calendario(curso_id: int) -> tuple[int, int]:
    """Genera o regenera el calendario de un curso a petición (RF-19).

    Returns:
        (número de sesiones, horas totales).
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-19
    try:
        curso = obtener_curso(curso_id)
        if not calendario.regenerar_calendario(curso):
            raise ErrorNegocio(
                "El curso ya tiene asistencia registrada; su calendario no se regenera."
            )
        db.session.commit()
        return calendario.resumen_calendario(curso.id)
    except Exception:
        db.session.rollback()
        raise
