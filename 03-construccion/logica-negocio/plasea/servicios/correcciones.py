"""Envío del registro, correcciones con motivo y bloqueo fuera de plazo
(RF-30, RF-31 y RF-32).

Ciclo de un curso en un corte: borrador (RF-28, RF-29) → enviado (RF-30) →
correcciones con motivo hasta el límite de corrección (RF-31) → cerrado
(RF-36, RF-37) → reapertura excepcional, solo para modificar lo existente
(RF-38). Fuera de esos momentos toda edición se rechaza con un mensaje (RF-32).
La información nunca se elimina: cada corrección guarda valor anterior, valor
nuevo, motivo, usuario y fecha en ``historial_notas`` o ``historial_ausencias``.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Iterable, Optional

from sqlalchemy import select

from plasea.modelos import (
    Ausencia,
    Corte,
    Curso,
    HistorialAusencia,
    HistorialNota,
    NotaCorte,
    ReaperturaCurso,
    RegistroCursoCorte,
    SesionClase,
    db,
)
from plasea.servicios import alertas, bitacora, registro_academico
from plasea.servicios.comunes import ErrorNegocio, ahora
from plasea.servicios.registro_academico import ErrorNotas

EVENTO_ENVIO = "envio_registro"
EVENTO_CORRECCION = "correccion"
MODO_CARGA = "carga"
MODO_CORRECCION = "correccion"
MODO_REAPERTURA = "reapertura"
MODO_BLOQUEADO = "bloqueado"
MOTIVO_MINIMO, MOTIVO_MAXIMO = 5, 500


@dataclass(frozen=True)
class ModoEdicion:
    """Qué puede hacer el profesor con un curso en un corte."""

    modo: str
    mensaje: Optional[str]
    registro: Optional[RegistroCursoCorte] = None
    reapertura: Optional[ReaperturaCurso] = None

    @property
    def permite_correccion(self) -> bool:
        """Correcciones con motivo: tras el envío o en una reapertura."""
        return self.modo in (MODO_CORRECCION, MODO_REAPERTURA)


def modo_segun_reglas(
    corte: Corte, estado: str, hay_reapertura: bool, hoy: dt.date
) -> tuple[str, Optional[str]]:
    """Regla pura del modo de edición (RF-30 a RF-32, RF-38)."""
    # Responsable: Islender Arturo Alfonso
    # RF-32
    if hay_reapertura:
        return (
            MODO_REAPERTURA,
            "Reapertura excepcional vigente: solo se modifican notas y asistencia ya "
            "registradas, con motivo.",
        )
    bloqueo = registro_academico.motivo_bloqueo_carga(corte, estado, hoy)
    if bloqueo is None:
        return MODO_CARGA, None
    if (
        estado == registro_academico.ESTADO_ENVIADO
        and corte.cerrado_en is None
        and hoy <= corte.limite_correccion
    ):
        return (
            MODO_CORRECCION,
            f"Registro enviado. Puede corregir con motivo hasta el "
            f"{corte.limite_correccion:%d/%m/%Y}.",
        )
    if estado == registro_academico.ESTADO_CERRADO:
        return (
            MODO_BLOQUEADO,
            f"El corte {corte.numero} está cerrado: no admite cambios. Ante una falla "
            "técnica, el Auditor académico puede reabrir el curso.",
        )
    return MODO_BLOQUEADO, bloqueo


def _registro(curso_id: int, corte_id: int) -> Optional[RegistroCursoCorte]:
    """Registro del curso en el corte, si existe."""
    # Responsable: Islender Arturo Alfonso
    # RF-30
    return db.session.scalar(
        select(RegistroCursoCorte).where(
            RegistroCursoCorte.curso_id == curso_id,
            RegistroCursoCorte.corte_id == corte_id,
        )
    )


def reapertura_vigente(registro_id: Optional[int]) -> Optional[ReaperturaCurso]:
    """Reapertura sin cerrar del registro (RF-38, RF-39)."""
    # Responsable: Islender Arturo Alfonso
    # RF-38
    if registro_id is None:
        return None
    return db.session.scalar(
        select(ReaperturaCurso).where(
            ReaperturaCurso.registro_curso_corte_id == registro_id,
            ReaperturaCurso.cerrada_en.is_(None),
        )
    )


def modo_edicion(curso: Curso, corte: Corte) -> ModoEdicion:
    """Modo de edición del curso en el corte con los datos de la base (RF-32)."""
    # Responsable: Islender Arturo Alfonso
    # RF-32
    registro = _registro(curso.id, corte.id)
    reapertura = reapertura_vigente(registro.id if registro else None)
    hoy = ahora().date()
    estado = registro_academico.estado_del_corte(corte, registro, hoy)
    modo, mensaje = modo_segun_reglas(corte, estado, reapertura is not None, hoy)
    return ModoEdicion(modo, mensaje, registro, reapertura)


def modos_del_curso(curso: Curso) -> dict[int, ModoEdicion]:
    """Modo de edición de cada corte del curso, por identificador de corte."""
    # Responsable: Islender Arturo Alfonso
    # RF-32
    return {
        corte.id: modo_edicion(curso, corte)
        for corte in registro_academico.cortes_del_periodo(curso.periodo_academico)
    }


# ---------------------------------------------------------------------------
# RF-30: envío del registro
# ---------------------------------------------------------------------------


def pendientes_envio(curso: Curso, corte: Corte) -> list[str]:
    """Lo que falta para enviar: notas y asistencia hasta el fin del corte (RF-30)."""
    # Responsable: Islender Arturo Alfonso
    # RF-30
    pendientes: list[str] = []
    sin_nota = [
        fila.nombres
        for fila in registro_academico.planilla_notas(curso, corte)
        if fila.nota is None
    ]
    if sin_nota:
        muestra = ", ".join(sin_nota[:5]) + (
            f" y {len(sin_nota) - 5} más" if len(sin_nota) > 5 else ""
        )
        pendientes.append(f"{len(sin_nota)} estudiante(s) sin nota: {muestra}.")
    hoy = ahora().date()
    sin_asistencia = list(
        db.session.scalars(
            select(SesionClase.fecha)
            .where(
                SesionClase.curso_id == curso.id,
                SesionClase.fecha >= corte.fecha_inicio,
                SesionClase.fecha <= corte.fecha_fin,
                SesionClase.asistencia_registrada_en.is_(None),
            )
            .order_by(SesionClase.fecha)
        )
    )
    futuras = [f for f in sin_asistencia if f > hoy]
    pasadas = [f for f in sin_asistencia if f <= hoy]
    if pasadas:
        fechas = ", ".join(f"{f:%d/%m}" for f in pasadas[:6])
        pendientes.append(
            f"{len(pasadas)} sesión(es) sin asistencia registrada ({fechas})."
        )
    if futuras:
        pendientes.append(
            f"Faltan {len(futuras)} sesión(es) por dictar hasta el fin del corte "
            f"({corte.fecha_fin:%d/%m/%Y})."
        )
    return pendientes


def enviar_registro(curso_id: int, numero_corte: int, profesor_id: int) -> int:
    """Envía el registro del curso en el corte y calcula las alertas (RF-30).

    Returns:
        Número de alertas calculadas.

    Raises:
        AccesoDenegado: el curso es de otro docente.
        ErrorNegocio: fuera de plazo, ya enviado o con datos pendientes (el
            mensaje lista lo pendiente).
    """
    # Responsable: Islender Arturo Alfonso
    # RF-30
    try:
        curso = registro_academico.obtener_curso_propio(curso_id, profesor_id)
        corte = registro_academico.corte_por_numero(curso, numero_corte)
        modo = modo_edicion(curso, corte)
        if modo.modo != MODO_CARGA:
            raise ErrorNegocio(modo.mensaje or "El registro no se puede enviar ahora.")
        pendientes = pendientes_envio(curso, corte)
        if pendientes:
            raise ErrorNegocio("No se envió. Falta: " + " ".join(pendientes))
        registro = modo.registro
        if registro is None:
            registro = RegistroCursoCorte(curso_id=curso.id, corte_id=corte.id)
            db.session.add(registro)
        registro.estado = registro_academico.ESTADO_ENVIADO
        registro.enviado_en = ahora()
        registro.enviado_por_usuario_id = profesor_id
        db.session.flush()
        total = alertas.recalcular(corte, [curso.id])
        bitacora.registrar_evento(
            EVENTO_ENVIO,
            usuario_id=profesor_id,
            entidad="registros_curso_corte",
            entidad_id=registro.id,
            detalle=f"Envío del corte {corte.numero}: {total} alertas calculadas",
        )
        db.session.commit()
        return total
    except Exception:
        db.session.rollback()
        raise


# ---------------------------------------------------------------------------
# RF-31: correcciones con motivo
# ---------------------------------------------------------------------------


def _validar_motivo(motivo: Optional[str]) -> str:
    """Motivo obligatorio de una corrección (RF-31)."""
    # Responsable: Islender Arturo Alfonso
    # RF-31
    limpio = " ".join((motivo or "").split())
    if len(limpio) < MOTIVO_MINIMO:
        raise ErrorNegocio("Escriba el motivo de la corrección (mínimo 5 caracteres).")
    if len(limpio) > MOTIVO_MAXIMO:
        raise ErrorNegocio("El motivo admite hasta 500 caracteres.")
    return limpio


def _modo_correccion(curso: Curso, corte: Corte) -> ModoEdicion:
    """Exige que el curso esté enviado y en plazo, o reabierto (RF-31, RF-32)."""
    # Responsable: Islender Arturo Alfonso
    # RF-32
    modo = modo_edicion(curso, corte)
    if modo.modo == MODO_CARGA:
        raise ErrorNegocio(
            "El registro aún no se ha enviado: modifique el borrador directamente."
        )
    if not modo.permite_correccion:
        raise ErrorNegocio(modo.mensaje or "Ya no se admiten correcciones.")
    return modo


def corregir_notas(
    curso_id: int,
    numero_corte: int,
    cambios: dict[int, tuple[str, str]],
    profesor_id: int,
) -> int:
    """Corrige notas ya registradas con un motivo por cada corrección (RF-31).

    Args:
        cambios: por inscripción, (nota escrita, motivo). Solo se procesan las
            notas que cambian.

    Returns:
        Número de notas corregidas.

    Raises:
        ErrorNotas: notas o motivos inválidos (nada se guarda).
        ErrorNegocio: fuera de plazo o sin cambios.
    """
    # Responsable: Islender Arturo Alfonso
    # RF-31
    try:
        curso = registro_academico.obtener_curso_propio(curso_id, profesor_id)
        corte = registro_academico.corte_por_numero(curso, numero_corte)
        modo = _modo_correccion(curso, corte)
        filas = {
            f.inscripcion_id: f for f in registro_academico.planilla_notas(curso, corte)
        }
        if not set(cambios) <= filas.keys():
            raise ErrorNegocio("Hay notas de estudiantes que no pertenecen al curso.")
        guardadas = {
            nota.inscripcion_id: nota
            for nota in db.session.scalars(
                select(NotaCorte).where(
                    NotaCorte.corte_id == corte.id,
                    NotaCorte.inscripcion_id.in_(list(filas) or [0]),
                )
            )
        }
        errores: dict[int, str] = {}
        aplicar: list[tuple[NotaCorte, object, str]] = []
        for inscripcion_id, (texto, motivo) in cambios.items():
            existente = guardadas.get(inscripcion_id)
            try:
                nueva = registro_academico.interpretar_nota(texto)
            except ErrorNegocio as fallo:
                errores[inscripcion_id] = fallo.mensaje
                continue
            if existente is None:
                if nueva is not None:
                    errores[inscripcion_id] = (
                        "No tiene nota registrada; una corrección solo modifica notas "
                        "existentes."
                    )
                continue
            if nueva is None:
                errores[inscripcion_id] = "La nota no se puede borrar."
                continue
            if nueva == existente.nota:
                continue
            try:
                aplicar.append((existente, nueva, _validar_motivo(motivo)))
            except ErrorNegocio as fallo:
                errores[inscripcion_id] = fallo.mensaje
        if errores:
            raise ErrorNotas(errores)
        if not aplicar:
            raise ErrorNegocio("No hay cambios en las notas.")
        reapertura_id = modo.reapertura.id if modo.reapertura else None
        for nota, nueva, motivo in aplicar:
            db.session.add(
                HistorialNota(
                    nota_corte_id=nota.id,
                    nota_anterior=nota.nota,
                    nota_nueva=nueva,
                    motivo=motivo,
                    usuario_id=profesor_id,
                    reapertura_curso_id=reapertura_id,
                )
            )
            nota.nota = nueva
            nota.registrada_por_usuario_id = profesor_id
        db.session.flush()
        alertas.recalcular_curso(curso.id, corte.numero)
        bitacora.registrar_evento(
            EVENTO_CORRECCION,
            usuario_id=profesor_id,
            entidad="notas_corte",
            entidad_id=modo.registro.id if modo.registro else None,
            detalle=(
                f"Corrección de {len(aplicar)} nota(s) del corte {corte.numero}"
                + (" en reapertura" if reapertura_id else "")
            ),
        )
        db.session.commit()
        return len(aplicar)
    except Exception:
        db.session.rollback()
        raise


def corregir_asistencia(
    curso_id: int,
    sesion_id: int,
    ausentes: Iterable[int],
    motivo: Optional[str],
    profesor_id: int,
) -> int:
    """Corrige la asistencia de una sesión ya registrada, con motivo (RF-31).

    En una reapertura (RF-38) solo se modifican ausencias existentes: no se
    puede marcar como ausente a quien no tenía registro de ausencia.

    Returns:
        Número de estudiantes cuya asistencia cambió.
    """
    # Responsable: Islender Arturo Alfonso
    # RF-31
    try:
        curso = registro_academico.obtener_curso_propio(curso_id, profesor_id)
        sesion = registro_academico.sesion_del_curso(curso, sesion_id)
        corte = registro_academico.corte_de_fecha(
            registro_academico.cortes_del_periodo(curso.periodo_academico),
            sesion.fecha,
        )
        if corte is None:
            raise ErrorNegocio("La sesión no pertenece a ningún corte.")
        modo = _modo_correccion(curso, corte)
        if sesion.asistencia_registrada_en is None:
            raise ErrorNegocio(
                "La sesión no tiene asistencia registrada; solo se corrige lo "
                "existente."
            )
        inscritos = {
            f.inscripcion_id
            for f in registro_academico.estudiantes_del_curso(curso.id, sesion.fecha)
        }
        marcados = set(ausentes)
        if not marcados <= inscritos:
            raise ErrorNegocio("Hay estudiantes marcados que no pertenecen al curso.")
        filas = {
            a.inscripcion_id: a
            for a in db.session.scalars(
                select(Ausencia).where(Ausencia.sesion_clase_id == sesion.id)
            )
        }
        cambios = [
            i
            for i in inscritos
            if (i in marcados) != bool(filas.get(i) and filas[i].ausente)
        ]
        if not cambios:
            raise ErrorNegocio("No hay cambios en la asistencia.")
        motivo_limpio = _validar_motivo(motivo)
        reapertura_id = modo.reapertura.id if modo.reapertura else None
        for inscripcion_id in cambios:
            ausencia = filas.get(inscripcion_id)
            nuevo = inscripcion_id in marcados
            if ausencia is None:
                if reapertura_id is not None:
                    raise ErrorNegocio(
                        "En una reapertura no se crean registros nuevos: solo se puede "
                        "quitar o restablecer una ausencia ya registrada."
                    )
                ausencia = Ausencia(
                    sesion_clase_id=sesion.id,
                    inscripcion_id=inscripcion_id,
                    ausente=True,
                    registrada_por_usuario_id=profesor_id,
                )
                db.session.add(ausencia)
                db.session.flush()
                anterior = False
            else:
                anterior = bool(ausencia.ausente)
                ausencia.ausente = nuevo
                ausencia.registrada_por_usuario_id = profesor_id
            db.session.add(
                HistorialAusencia(
                    ausencia_id=ausencia.id,
                    ausente_anterior=anterior,
                    ausente_nuevo=nuevo,
                    motivo=motivo_limpio,
                    usuario_id=profesor_id,
                    reapertura_curso_id=reapertura_id,
                )
            )
        db.session.flush()
        alertas.recalcular_curso(curso.id, corte.numero)
        bitacora.registrar_evento(
            EVENTO_CORRECCION,
            usuario_id=profesor_id,
            entidad="sesiones_clase",
            entidad_id=sesion.id,
            detalle=(
                f"Corrección de asistencia del {sesion.fecha:%d/%m/%Y}: "
                f"{len(cambios)} estudiante(s)"
                + (" en reapertura" if reapertura_id else "")
            ),
        )
        db.session.commit()
        return len(cambios)
    except Exception:
        db.session.rollback()
        raise
