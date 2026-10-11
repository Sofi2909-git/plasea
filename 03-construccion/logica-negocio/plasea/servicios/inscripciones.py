"""Inscripción y retiro de estudiantes en cursos de un período (RF-23).

El estudiante participa en un período mediante su matrícula (con el semestre de
la carrera que cursa) y en cada curso mediante una inscripción. El retiro de un
curso conserva la fila (fecha de retiro).
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from plasea.modelos import (
    Curso,
    Estudiante,
    Inscripcion,
    MatriculaPeriodo,
    PeriodoAcademico,
    db,
)
from plasea.servicios import bitacora, estudiantes
from plasea.servicios.comunes import ErrorNegocio

SEMESTRE_MINIMO, SEMESTRE_MAXIMO = 1, 10


def fecha_referencia(periodo: PeriodoAcademico) -> dt.date:
    """Fecha en la que se exige el estado activo: hoy, o el fin de un período pasado."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-23
    return min(estudiantes.hoy(), periodo.fecha_fin)


def verificar_inscribible(estudiante: Estudiante, periodo: PeriodoAcademico) -> None:
    """Aplica las reglas de estado de RF-22 y RF-23 antes de inscribir.

    - RF-22: si al iniciar el período su estado es graduado, retirado formal o
      cancelado, no se inscribe (período posterior a la fecha efectiva).
    - RF-23: solo se inscriben estudiantes con estado vigente "activo".

    Raises:
        ErrorNegocio: con el motivo.
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-23
    al_inicio = estudiantes.estado_en_fecha(estudiante.id, periodo.fecha_inicio)
    if (
        al_inicio is not None
        and al_inicio.estado_estudiante.codigo in estudiantes.ESTADOS_TERMINALES
    ):
        raise ErrorNegocio(
            f"El estudiante está en estado «{al_inicio.estado_estudiante.nombre}» "
            f"desde el {al_inicio.fecha_efectiva:%d/%m/%Y}; no se puede inscribir en "
            f"el período {periodo.identificador}."
        )
    vigente = estudiantes.estado_en_fecha(estudiante.id, fecha_referencia(periodo))
    if vigente is None or vigente.estado_estudiante.codigo != estudiantes.ESTADO_ACTIVO:
        nombre = vigente.estado_estudiante.nombre if vigente else "sin estado"
        raise ErrorNegocio(
            f"Solo se inscriben estudiantes activos. Estado actual: {nombre}."
        )


def inscritos_del_curso(curso_id: int) -> list[Inscripcion]:
    """Inscripciones del curso (vigentes y retiradas) con el estudiante cargado."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-23
    return list(
        db.session.scalars(
            select(Inscripcion)
            .join(
                MatriculaPeriodo,
                MatriculaPeriodo.id == Inscripcion.matricula_periodo_id,
            )
            .join(Estudiante, Estudiante.id == MatriculaPeriodo.estudiante_id)
            .options(
                joinedload(Inscripcion.matricula_periodo).joinedload(
                    MatriculaPeriodo.estudiante
                )
            )
            .where(Inscripcion.curso_id == curso_id)
            .order_by(Inscripcion.retirada_en.is_not(None), Estudiante.nombres)
        )
    )


def inscripciones_del_estudiante(estudiante_id: int) -> list[Inscripcion]:
    """Inscripciones del estudiante en todos los períodos, de la más reciente."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-23
    return list(
        db.session.scalars(
            select(Inscripcion)
            .join(
                MatriculaPeriodo,
                MatriculaPeriodo.id == Inscripcion.matricula_periodo_id,
            )
            .join(
                PeriodoAcademico,
                PeriodoAcademico.id == Inscripcion.periodo_academico_id,
            )
            .options(
                joinedload(Inscripcion.curso).joinedload(Curso.asignatura),
                joinedload(Inscripcion.curso).joinedload(Curso.periodo_academico),
                joinedload(Inscripcion.matricula_periodo),
            )
            .where(MatriculaPeriodo.estudiante_id == estudiante_id)
            .order_by(PeriodoAcademico.fecha_inicio.desc(), Inscripcion.id)
        )
    )


def _matricula(estudiante_id: int, periodo_id: int) -> Optional[MatriculaPeriodo]:
    """Matrícula del estudiante en el período, si existe."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-23
    return db.session.scalar(
        select(MatriculaPeriodo).where(
            MatriculaPeriodo.estudiante_id == estudiante_id,
            MatriculaPeriodo.periodo_academico_id == periodo_id,
        )
    )


def inscribir(
    curso_id: int, codigo_estudiante: str, semestre_cursado: int, actor_id: int
) -> Inscripcion:
    """Inscribe un estudiante en un curso registrando el semestre que cursa (RF-23).

    Si el estudiante ya está matriculado en el período, el semestre debe
    coincidir con el registrado.

    Raises:
        ErrorNegocio: estudiante inexistente o no activo, semestre inválido o
            inscripción repetida en el mismo curso.
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-23
    try:
        curso = db.session.get(Curso, curso_id)
        if curso is None:
            raise ErrorNegocio("El curso solicitado no existe.")
        periodo = curso.periodo_academico
        estudiante = estudiantes.buscar_por_codigo(codigo_estudiante)
        if estudiante is None:
            raise ErrorNegocio("No existe un estudiante con ese código.")
        if not SEMESTRE_MINIMO <= semestre_cursado <= SEMESTRE_MAXIMO:
            raise ErrorNegocio("El semestre cursado debe estar entre 1 y 10.")
        verificar_inscribible(estudiante, periodo)

        matricula = _matricula(estudiante.id, periodo.id)
        if matricula is None:
            matricula = MatriculaPeriodo(
                estudiante_id=estudiante.id,
                periodo_academico_id=periodo.id,
                semestre_cursado=semestre_cursado,
            )
            db.session.add(matricula)
            db.session.flush()
        elif matricula.semestre_cursado != semestre_cursado:
            raise ErrorNegocio(
                f"El estudiante ya está matriculado en {periodo.identificador} "
                f"cursando el semestre {matricula.semestre_cursado}."
            )

        existente = db.session.scalar(
            select(Inscripcion).where(
                Inscripcion.matricula_periodo_id == matricula.id,
                Inscripcion.curso_id == curso.id,
            )
        )
        if existente is not None:
            detalle = (
                "Ya está inscrito en este curso."
                if existente.retirada_en is None
                else f"Se retiró de este curso el {existente.retirada_en:%d/%m/%Y}; "
                "no se inscribe dos veces en el mismo curso."
            )
            raise ErrorNegocio(detalle)

        inscripcion = Inscripcion(
            matricula_periodo_id=matricula.id,
            curso_id=curso.id,
            periodo_academico_id=periodo.id,
        )
        db.session.add(inscripcion)
        db.session.flush()
        bitacora.registrar_evento(
            bitacora.EVENTO_CAMBIO_ADMINISTRATIVO,
            usuario_id=actor_id,
            entidad="inscripciones",
            entidad_id=inscripcion.id,
            detalle=f"Inscripción del estudiante {estudiante.codigo} en un curso",
        )
        db.session.commit()
        return inscripcion
    except Exception:
        db.session.rollback()
        raise


def retirar(inscripcion_id: int, actor_id: int) -> Inscripcion:
    """Retira al estudiante del curso; la inscripción se conserva (RF-23)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-23
    try:
        inscripcion = db.session.get(Inscripcion, inscripcion_id)
        if inscripcion is None:
            raise ErrorNegocio("La inscripción no existe.")
        if inscripcion.retirada_en is not None:
            raise ErrorNegocio("El estudiante ya se había retirado de este curso.")
        inscripcion.retirada_en = estudiantes.hoy()
        bitacora.registrar_evento(
            bitacora.EVENTO_CAMBIO_ADMINISTRATIVO,
            usuario_id=actor_id,
            entidad="inscripciones",
            entidad_id=inscripcion.id,
            detalle="Retiro del curso (la inscripción se conserva)",
        )
        db.session.commit()
        return inscripcion
    except Exception:
        db.session.rollback()
        raise
