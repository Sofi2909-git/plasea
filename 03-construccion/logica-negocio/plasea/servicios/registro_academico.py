"""Registro de asistencia y notas del profesor (RF-26 a RF-29).

- RF-26: cursos del profesor en el período en curso con el estado de cada corte.
- RF-27: estudiantes inscritos (solo código y nombre).
- RF-28: asistencia por sesión marcando solo a los ausentes; sin fila = presente.
- RF-29: nota consolidada por corte (1,0 a 5,0 con un decimal) con borrador.

El envío del registro (RF-30), la corrección con motivo (RF-31), el bloqueo de
cortes cerrados con reapertura (RF-32, RF-38) y el cierre (RF-36, RF-37) son de
otros módulos; aquí solo se respeta el estado que dejan en
``registros_curso_corte`` y en ``cortes``.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload, selectinload

from plasea.modelos import (
    Asignatura,
    Ausencia,
    Corte,
    Curso,
    Estudiante,
    Inscripcion,
    MatriculaPeriodo,
    NotaCorte,
    PeriodoAcademico,
    RegistroCursoCorte,
    SesionClase,
    db,
)
from plasea.servicios.comunes import ErrorNegocio, ahora

ESTADO_PENDIENTE = "pendiente"
ESTADO_ENVIADO = "enviado"
ESTADO_CERRADO = "cerrado"
NOMBRES_ESTADO = {
    ESTADO_PENDIENTE: "Pendiente",
    ESTADO_ENVIADO: "Enviado",
    ESTADO_CERRADO: "Cerrado",
}
NOTA_MINIMA, NOTA_MAXIMA = Decimal("1.0"), Decimal("5.0")
_PATRON_NOTA = re.compile(r"^(\d+)(?:\.(\d+))?$")


class AccesoDenegado(Exception):
    """El curso existe pero no pertenece al profesor autenticado (RF-02)."""


class ErrorNotas(ErrorNegocio):
    """Una o más notas no son válidas; no se guarda ninguna (RF-29)."""

    def __init__(self, errores: dict[int, str]) -> None:
        super().__init__(
            "Revise las notas marcadas: no se guardó ninguna hasta corregirlas."
        )
        self.errores = errores


@dataclass(frozen=True)
class EstadoCorte:
    """Estado de un corte para un curso, como lo ve el profesor (RF-26)."""

    corte: Corte
    estado: str

    @property
    def nombre(self) -> str:
        """Nombre visible del estado."""
        return NOMBRES_ESTADO[self.estado]


@dataclass(frozen=True)
class ResumenCurso:
    """Fila de "Mis cursos" (RF-26)."""

    curso: Curso
    inscritos: int
    horas_totales: int
    estados: list[EstadoCorte]
    corte_en_carga: Optional[Corte]
    sesiones_por_registrar: int
    notas_faltantes: Optional[int]


@dataclass(frozen=True)
class FilaEstudiante:
    """Estudiante inscrito sin datos personales innecesarios (RF-27)."""

    inscripcion_id: int
    codigo: str
    nombres: str


@dataclass(frozen=True)
class FilaSesion:
    """Sesión del calendario con su estado de asistencia (RF-28)."""

    sesion: SesionClase
    corte_numero: Optional[int]
    ausentes: int
    registrada: bool
    bloqueo: Optional[str]

    @property
    def dictada(self) -> bool:
        """La sesión ya ocurrió (o es hoy)."""
        return self.sesion.fecha <= _hoy()


@dataclass(frozen=True)
class FilaNota:
    """Fila de la planilla de notas de un corte (RF-29)."""

    inscripcion_id: int
    codigo: str
    nombres: str
    nota: Optional[Decimal]


@dataclass
class ResultadoAsistencia:
    """Resumen de una asistencia guardada (RF-28)."""

    ausentes: int
    horas_por_ausente: int
    cambios: int = 0
    nombres_ausentes: list[str] = field(default_factory=list)


def _hoy() -> dt.date:
    """Fecha actual de Colombia."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-28
    return ahora().date()


# ---------------------------------------------------------------------------
# Reglas puras (sin base de datos): estados y plazos
# ---------------------------------------------------------------------------


def estado_del_corte(
    corte: Corte, registro: Optional[RegistroCursoCorte], hoy: dt.date
) -> str:
    """Estado del corte para un curso: pendiente, enviado o cerrado (RF-26).

    Coincide con RF-30 (envío), RF-36 (cierre manual) y RF-37 (cierre
    automático al vencer el límite de corrección): un corte con el límite de
    corrección vencido se muestra cerrado aunque el proceso automático aún no
    haya marcado la fecha de cierre.
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-26
    if corte.cerrado_en is not None or hoy > corte.limite_correccion:
        return ESTADO_CERRADO
    if registro is not None and registro.estado in (ESTADO_CERRADO, "sin_registro"):
        return ESTADO_CERRADO
    if registro is not None and registro.estado == ESTADO_ENVIADO:
        return ESTADO_ENVIADO
    return ESTADO_PENDIENTE


def motivo_bloqueo_carga(corte: Corte, estado: str, hoy: dt.date) -> Optional[str]:
    """Motivo por el que no se puede cargar en el corte; ``None`` si se puede.

    El plazo de carga va del inicio del corte a su límite de carga (RF-28,
    RF-29). Después del envío solo se corrige con motivo (RF-31).
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-29
    etiqueta = f"El corte {corte.numero}"
    if estado == ESTADO_CERRADO:
        return f"{etiqueta} está cerrado; ya no admite cambios."
    if estado == ESTADO_ENVIADO:
        return (
            f"{etiqueta} ya se envió. Los cambios se hacen como corrección con "
            "motivo hasta el límite de corrección."
        )
    if hoy < corte.fecha_inicio:
        return f"{etiqueta} inicia el {corte.fecha_inicio:%d/%m/%Y}."
    if hoy > corte.limite_carga:
        return (
            f"Venció el plazo de carga de {etiqueta.lower()} "
            f"({corte.limite_carga:%d/%m/%Y})."
        )
    return None


def corte_de_fecha(cortes: Iterable[Corte], fecha: dt.date) -> Optional[Corte]:
    """Corte al que pertenece una fecha de clase (entre su inicio y su fin)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-28
    for corte in cortes:
        if corte.fecha_inicio <= fecha <= corte.fecha_fin:
            return corte
    return None


def motivo_bloqueo_asistencia(
    sesion: SesionClase, corte: Optional[Corte], estado: Optional[str], hoy: dt.date
) -> Optional[str]:
    """Motivo por el que no se puede registrar la asistencia de una sesión (RF-28).

    Solo sesiones ya dictadas y dentro del plazo de su corte.
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-28
    if sesion.fecha > hoy:
        return "La sesión aún no se ha dictado."
    if corte is None or estado is None:
        return "La sesión no pertenece a ningún corte del período."
    return motivo_bloqueo_carga(corte, estado, hoy)


def interpretar_nota(texto: Optional[str]) -> Optional[Decimal]:
    """Convierte el texto escrito por el profesor en una nota (RF-29).

    Acepta coma o punto decimal. Vacío = sin nota.

    Raises:
        ErrorNegocio: fuera de 1,0 a 5,0 o con más de un decimal.
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-29
    limpio = (texto or "").strip().replace(",", ".")
    if not limpio:
        return None
    coincidencia = _PATRON_NOTA.match(limpio)
    if coincidencia is None:
        raise ErrorNegocio("Escriba un número, por ejemplo 3,5.")
    if coincidencia.group(2) is not None and len(coincidencia.group(2)) > 1:
        raise ErrorNegocio("Use un solo decimal, por ejemplo 3,5.")
    nota = Decimal(limpio).quantize(Decimal("0.1"))
    if not NOTA_MINIMA <= nota <= NOTA_MAXIMA:
        raise ErrorNegocio("La nota debe estar entre 1,0 y 5,0.")
    return nota


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------


def obtener_curso_propio(curso_id: int, profesor_id: int) -> Curso:
    """Curso del profesor con asignatura, período, cortes y horario (RF-27).

    Raises:
        ErrorNegocio: el curso no existe.
        AccesoDenegado: el curso es de otro docente.
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-27
    curso = db.session.scalar(
        select(Curso)
        .options(
            joinedload(Curso.asignatura),
            joinedload(Curso.periodo_academico).selectinload(PeriodoAcademico.cortes),
            selectinload(Curso.bloques_horario),
        )
        .where(Curso.id == curso_id)
    )
    if curso is None:
        raise ErrorNegocio("El curso solicitado no existe.")
    if curso.profesor_usuario_id != profesor_id:
        raise AccesoDenegado()
    return curso


def cortes_del_periodo(periodo: PeriodoAcademico) -> list[Corte]:
    """Cortes del período ordenados por número."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-26
    return sorted(periodo.cortes, key=lambda corte: corte.numero)


def _registros(curso_ids: list[int]) -> dict[tuple[int, int], RegistroCursoCorte]:
    """Registros curso-corte de varios cursos, en una sola consulta."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-26
    if not curso_ids:
        return {}
    filas = db.session.scalars(
        select(RegistroCursoCorte).where(RegistroCursoCorte.curso_id.in_(curso_ids))
    )
    return {(r.curso_id, r.corte_id): r for r in filas}


def estados_de_cortes(
    curso: Curso, registros: Optional[dict[tuple[int, int], RegistroCursoCorte]] = None
) -> list[EstadoCorte]:
    """Estado de los 3 cortes de un curso (RF-26)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-26
    if registros is None:
        registros = _registros([curso.id])
    hoy = _hoy()
    return [
        EstadoCorte(
            corte, estado_del_corte(corte, registros.get((curso.id, corte.id)), hoy)
        )
        for corte in cortes_del_periodo(curso.periodo_academico)
    ]


def corte_en_carga(estados: list[EstadoCorte]) -> Optional[Corte]:
    """Primer corte con el plazo de carga abierto para el curso."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-26
    hoy = _hoy()
    for estado in estados:
        if motivo_bloqueo_carga(estado.corte, estado.estado, hoy) is None:
            return estado.corte
    return None


def cursos_del_profesor(
    profesor_id: int, periodo: Optional[PeriodoAcademico]
) -> list[ResumenCurso]:
    """Cursos del profesor en el período con horario y estado por corte (RF-26).

    Usa cinco consultas fijas (cursos, inscritos, horas, pendientes y notas)
    sin importar cuántos cursos tenga el profesor.
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-26
    if periodo is None:
        return []
    lista = list(
        db.session.scalars(
            select(Curso)
            .join(Curso.asignatura)
            .options(
                joinedload(Curso.asignatura),
                joinedload(Curso.periodo_academico).selectinload(
                    PeriodoAcademico.cortes
                ),
                selectinload(Curso.bloques_horario),
            )
            .where(
                Curso.profesor_usuario_id == profesor_id,
                Curso.periodo_academico_id == periodo.id,
            )
            .order_by(Asignatura.nombre, Curso.codigo)
        ).unique()
    )
    ids = [curso.id for curso in lista]
    if not ids:
        return []
    hoy = _hoy()
    inscritos = dict(
        db.session.execute(
            select(Inscripcion.curso_id, func.count(Inscripcion.id))
            .where(Inscripcion.curso_id.in_(ids), Inscripcion.retirada_en.is_(None))
            .group_by(Inscripcion.curso_id)
        ).all()
    )
    horas = dict(
        db.session.execute(
            select(SesionClase.curso_id, func.sum(SesionClase.duracion_horas))
            .where(SesionClase.curso_id.in_(ids))
            .group_by(SesionClase.curso_id)
        ).all()
    )
    registros = _registros(ids)
    resumenes: list[ResumenCurso] = []
    estados_por_curso = {
        curso.id: estados_de_cortes(curso, registros) for curso in lista
    }
    abiertos = {
        cid: corte_en_carga(estados) for cid, estados in estados_por_curso.items()
    }

    # Sesiones dictadas sin asistencia registrada dentro de un corte con plazo abierto.
    pendientes: dict[int, int] = {}
    condiciones = [
        (SesionClase.curso_id == cid)
        & (SesionClase.fecha >= corte.fecha_inicio)
        & (SesionClase.fecha <= min(corte.fecha_fin, hoy))
        for cid, corte in abiertos.items()
        if corte is not None
    ]
    if condiciones:
        pendientes = dict(
            db.session.execute(
                select(SesionClase.curso_id, func.count(SesionClase.id))
                .where(
                    or_(*condiciones), SesionClase.asistencia_registrada_en.is_(None)
                )
                .group_by(SesionClase.curso_id)
            ).all()
        )
    # Notas registradas en el corte con plazo abierto.
    con_nota: dict[int, int] = {}
    pares = [(cid, corte.id) for cid, corte in abiertos.items() if corte is not None]
    if pares:
        con_nota = dict(
            db.session.execute(
                select(Inscripcion.curso_id, func.count(NotaCorte.id))
                .join(NotaCorte, NotaCorte.inscripcion_id == Inscripcion.id)
                .where(
                    or_(
                        *(
                            (Inscripcion.curso_id == cid)
                            & (NotaCorte.corte_id == corte_id)
                            for cid, corte_id in pares
                        )
                    ),
                    Inscripcion.retirada_en.is_(None),
                )
                .group_by(Inscripcion.curso_id)
            ).all()
        )
    for curso in lista:
        abierto = abiertos[curso.id]
        total = int(inscritos.get(curso.id, 0))
        resumenes.append(
            ResumenCurso(
                curso=curso,
                inscritos=total,
                horas_totales=int(horas.get(curso.id) or 0),
                estados=estados_por_curso[curso.id],
                corte_en_carga=abierto,
                sesiones_por_registrar=int(pendientes.get(curso.id, 0)),
                notas_faltantes=(
                    total - int(con_nota.get(curso.id, 0)) if abierto else None
                ),
            )
        )
    return resumenes


def estudiantes_del_curso(
    curso_id: int, en_fecha: Optional[dt.date] = None
) -> list[FilaEstudiante]:
    """Inscritos vigentes del curso: código y nombre, ordenados por nombre (RF-27).

    Con ``en_fecha`` incluye a quienes se retiraron después de esa fecha (para
    la asistencia de una sesión pasada).
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-27
    vigente = (
        Inscripcion.retirada_en.is_(None)
        if en_fecha is None
        else or_(Inscripcion.retirada_en.is_(None), Inscripcion.retirada_en > en_fecha)
    )
    filas = db.session.execute(
        select(Inscripcion.id, Estudiante.codigo, Estudiante.nombres)
        .join(MatriculaPeriodo, MatriculaPeriodo.id == Inscripcion.matricula_periodo_id)
        .join(Estudiante, Estudiante.id == MatriculaPeriodo.estudiante_id)
        .where(Inscripcion.curso_id == curso_id, vigente)
        .order_by(Estudiante.nombres, Estudiante.codigo)
    )
    return [FilaEstudiante(*fila) for fila in filas]


def sesiones_con_estado(curso: Curso, estados: list[EstadoCorte]) -> list[FilaSesion]:
    """Calendario del curso con ausentes y disponibilidad de registro (RF-28)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-28
    hoy = _hoy()
    sesiones = list(
        db.session.scalars(
            select(SesionClase)
            .where(SesionClase.curso_id == curso.id)
            .order_by(SesionClase.fecha, SesionClase.hora_inicio)
        )
    )
    ausentes = dict(
        db.session.execute(
            select(Ausencia.sesion_clase_id, func.count(Ausencia.id))
            .join(SesionClase, SesionClase.id == Ausencia.sesion_clase_id)
            .where(SesionClase.curso_id == curso.id, Ausencia.ausente.is_(True))
            .group_by(Ausencia.sesion_clase_id)
        ).all()
    )
    por_corte = {estado.corte.id: estado.estado for estado in estados}
    cortes = [estado.corte for estado in estados]
    filas: list[FilaSesion] = []
    for sesion in sesiones:
        corte = corte_de_fecha(cortes, sesion.fecha)
        estado = por_corte.get(corte.id) if corte else None
        filas.append(
            FilaSesion(
                sesion=sesion,
                corte_numero=corte.numero if corte else None,
                ausentes=int(ausentes.get(sesion.id, 0)),
                registrada=sesion.asistencia_registrada_en is not None,
                bloqueo=motivo_bloqueo_asistencia(sesion, corte, estado, hoy),
            )
        )
    return filas


def sesion_del_curso(curso: Curso, sesion_id: int) -> SesionClase:
    """Sesión del calendario del curso.

    Raises:
        ErrorNegocio: la sesión no existe o es de otro curso.
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-28
    sesion = db.session.get(SesionClase, sesion_id)
    if sesion is None or sesion.curso_id != curso.id:
        raise ErrorNegocio("La sesión no pertenece a este curso.")
    return sesion


def estado_de_sesion(
    curso: Curso, sesion: SesionClase
) -> tuple[Optional[Corte], Optional[str], Optional[str]]:
    """Corte de la sesión, su estado y el motivo de bloqueo (si lo hay)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-28
    corte = corte_de_fecha(cortes_del_periodo(curso.periodo_academico), sesion.fecha)
    estado = None
    if corte is not None:
        registro = _registros([curso.id]).get((curso.id, corte.id))
        estado = estado_del_corte(corte, registro, _hoy())
    return corte, estado, motivo_bloqueo_asistencia(sesion, corte, estado, _hoy())


def ausentes_de_sesion(sesion_id: int) -> set[int]:
    """Inscripciones marcadas como ausentes en la sesión (fila con ausente = 1)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-28
    return set(
        db.session.scalars(
            select(Ausencia.inscripcion_id).where(
                Ausencia.sesion_clase_id == sesion_id, Ausencia.ausente.is_(True)
            )
        )
    )


def _asegurar_registro(curso_id: int, corte_id: int) -> None:
    """Crea el registro curso-corte en estado pendiente (borrador) si no existe."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-29
    existe = db.session.scalar(
        select(RegistroCursoCorte.id).where(
            RegistroCursoCorte.curso_id == curso_id,
            RegistroCursoCorte.corte_id == corte_id,
        )
    )
    if existe is None:
        db.session.add(
            RegistroCursoCorte(
                curso_id=curso_id, corte_id=corte_id, estado=ESTADO_PENDIENTE
            )
        )


# ---------------------------------------------------------------------------
# RF-28: registrar asistencia
# ---------------------------------------------------------------------------


def registrar_asistencia(
    curso_id: int, sesion_id: int, ausentes: Iterable[int], profesor_id: int
) -> ResultadoAsistencia:
    """Registra la asistencia de una sesión marcando solo a los ausentes (RF-28).

    Los no marcados quedan presentes. A cada ausente se le cargan las horas
    completas de la sesión (columna calculada ``duracion_horas``). Antes del
    envío, desmarcar a un ausente pone ``ausente = 0``: la fila no se elimina.

    Raises:
        AccesoDenegado: el curso es de otro docente.
        ErrorNegocio: sesión futura, fuera de plazo, corte enviado o cerrado, o
            estudiantes que no pertenecen al curso.
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-28
    try:
        curso = obtener_curso_propio(curso_id, profesor_id)
        sesion = sesion_del_curso(curso, sesion_id)
        corte, _estado, bloqueo = estado_de_sesion(curso, sesion)
        if bloqueo is not None or corte is None:
            raise ErrorNegocio(bloqueo or "La sesión no pertenece a ningún corte.")
        inscritos = {
            fila.inscripcion_id: fila.nombres
            for fila in estudiantes_del_curso(curso.id, en_fecha=sesion.fecha)
        }
        marcados = set(ausentes)
        if not marcados <= inscritos.keys():
            raise ErrorNegocio("Hay estudiantes marcados que no pertenecen al curso.")

        existentes = {
            ausencia.inscripcion_id: ausencia
            for ausencia in db.session.scalars(
                select(Ausencia).where(Ausencia.sesion_clase_id == sesion.id)
            )
        }
        cambios = 0
        for inscripcion_id, ausencia in existentes.items():
            debe_estar_ausente = inscripcion_id in marcados
            if bool(ausencia.ausente) != debe_estar_ausente:
                ausencia.ausente = debe_estar_ausente
                ausencia.registrada_por_usuario_id = profesor_id
                cambios += 1
        nuevos = marcados - existentes.keys()
        db.session.add_all(
            Ausencia(
                sesion_clase_id=sesion.id,
                inscripcion_id=inscripcion_id,
                ausente=True,
                registrada_por_usuario_id=profesor_id,
            )
            for inscripcion_id in nuevos
        )
        cambios += len(nuevos)
        sesion.asistencia_registrada_por_usuario_id = profesor_id
        sesion.asistencia_registrada_en = ahora()
        _asegurar_registro(curso.id, corte.id)
        db.session.commit()
        return ResultadoAsistencia(
            ausentes=len(marcados),
            horas_por_ausente=int(sesion.duracion_horas or 0),
            cambios=cambios,
            nombres_ausentes=sorted(inscritos[i] for i in marcados),
        )
    except Exception:
        db.session.rollback()
        raise


# ---------------------------------------------------------------------------
# RF-29: registrar notas
# ---------------------------------------------------------------------------


def corte_por_numero(curso: Curso, numero: int) -> Corte:
    """Corte del período del curso por su número (1 a 3).

    Raises:
        ErrorNegocio: el período no tiene ese corte.
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-29
    for corte in curso.periodo_academico.cortes:
        if corte.numero == numero:
            return corte
    raise ErrorNegocio(f"El período no tiene definido el corte {numero}.")


def planilla_notas(curso: Curso, corte: Corte) -> list[FilaNota]:
    """Inscritos vigentes con su nota del corte, si ya la tienen (RF-29)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-29
    filas = db.session.execute(
        select(Inscripcion.id, Estudiante.codigo, Estudiante.nombres, NotaCorte.nota)
        .join(MatriculaPeriodo, MatriculaPeriodo.id == Inscripcion.matricula_periodo_id)
        .join(Estudiante, Estudiante.id == MatriculaPeriodo.estudiante_id)
        .outerjoin(
            NotaCorte,
            (NotaCorte.inscripcion_id == Inscripcion.id)
            & (NotaCorte.corte_id == corte.id),
        )
        .where(Inscripcion.curso_id == curso.id, Inscripcion.retirada_en.is_(None))
        .order_by(Estudiante.nombres, Estudiante.codigo)
    )
    return [FilaNota(*fila) for fila in filas]


def estado_de_notas(curso: Curso, corte: Corte) -> tuple[str, Optional[str]]:
    """Estado del corte para el curso y motivo de bloqueo de la carga."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-29
    registro = _registros([curso.id]).get((curso.id, corte.id))
    estado = estado_del_corte(corte, registro, _hoy())
    return estado, motivo_bloqueo_carga(corte, estado, _hoy())


def guardar_notas(
    curso_id: int, numero_corte: int, valores: dict[int, str], profesor_id: int
) -> tuple[int, int]:
    """Guarda en borrador las notas de un corte (RF-29).

    Todo o nada: si una nota es inválida no se guarda ninguna. Un campo vacío
    deja al estudiante sin nota; una nota ya guardada no se puede borrar
    (la información académica no se elimina), solo cambiar mientras el
    registro esté en borrador.

    Returns:
        (estudiantes con nota, estudiantes sin nota).

    Raises:
        AccesoDenegado: el curso es de otro docente.
        ErrorNotas: notas inválidas, con el motivo por estudiante.
        ErrorNegocio: fuera del plazo de carga o corte enviado o cerrado.
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-29
    try:
        curso = obtener_curso_propio(curso_id, profesor_id)
        corte = corte_por_numero(curso, numero_corte)
        _estado, bloqueo = estado_de_notas(curso, corte)
        if bloqueo is not None:
            raise ErrorNegocio(bloqueo)
        filas = planilla_notas(curso, corte)
        ids_validos = {fila.inscripcion_id for fila in filas}
        if not set(valores) <= ids_validos:
            raise ErrorNegocio("Hay notas de estudiantes que no pertenecen al curso.")

        errores: dict[int, str] = {}
        nuevas: dict[int, Decimal] = {}
        for fila in filas:
            try:
                nota = interpretar_nota(valores.get(fila.inscripcion_id))
            except ErrorNegocio as fallo:
                errores[fila.inscripcion_id] = fallo.mensaje
                continue
            if nota is None and fila.nota is not None:
                errores[fila.inscripcion_id] = (
                    "La nota guardada no se puede borrar; escriba el valor correcto."
                )
            elif nota is not None:
                nuevas[fila.inscripcion_id] = nota
        if errores:
            raise ErrorNotas(errores)

        guardadas = {
            nota.inscripcion_id: nota
            for nota in db.session.scalars(
                select(NotaCorte).where(
                    NotaCorte.corte_id == corte.id,
                    NotaCorte.inscripcion_id.in_(ids_validos or {0}),
                )
            )
        }
        for inscripcion_id, valor in nuevas.items():
            existente = guardadas.get(inscripcion_id)
            if existente is None:
                db.session.add(
                    NotaCorte(
                        inscripcion_id=inscripcion_id,
                        corte_id=corte.id,
                        nota=valor,
                        registrada_por_usuario_id=profesor_id,
                    )
                )
            elif existente.nota != valor:
                existente.nota = valor
                existente.registrada_por_usuario_id = profesor_id
        _asegurar_registro(curso.id, corte.id)
        db.session.commit()
        con_nota = len(nuevas)
        return con_nota, len(filas) - con_nota
    except Exception:
        db.session.rollback()
        raise
