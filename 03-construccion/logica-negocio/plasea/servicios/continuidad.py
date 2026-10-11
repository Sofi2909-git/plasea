"""Continuidad y deserción (RF-49 a RF-53).

- RF-49: cada estudiante inscrito en un período se clasifica según el período
  siguiente: continúa (tiene matrícula), graduado, aplazó (estado vigente al
  inicio del siguiente) o no continúa.
- RF-50: índice = no continúan / (inscritos − graduados − aplazados).
- RF-51: el mismo cálculo por cohorte de ingreso y por semestre cursado; cada
  grupo se reconstruye con las filas de RF-49, así los grupos suman el total.
- RF-52: causa opcional de una lista fija, con historial (cada cambio agrega
  una fila; la vigente es la última).
- RF-53: lista de quienes no continuaron con filtros.

La clasificación sale de una sola consulta (matrículas del período, estado
vigente con una función de ventana, matrícula en el siguiente y causa vigente).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Optional

from sqlalchemy import func, select

from plasea.modelos import (
    CausaNoContinuidad,
    Estudiante,
    MatriculaPeriodo,
    PeriodoAcademico,
    ProgramaAcademico,
    RegistroCausaNoContinuidad,
    Usuario,
    db,
)
from plasea.servicios import bitacora, calculos, estudiantes
from plasea.servicios.comunes import ErrorNegocio

CONTINUA = "continua"
NO_CONTINUA = "no_continua"
GRADUADO = "graduado"
APLAZADO = "aplazado"
NOMBRES_CLASIFICACION = {
    CONTINUA: "Continúa",
    NO_CONTINUA: "No continúa",
    GRADUADO: "Graduado",
    APLAZADO: "Aplazó",
}
SIN_CAUSA = "sin_causa"


@dataclass(frozen=True)
class FilaContinuidad:
    """Un estudiante inscrito en el período y su clasificación (RF-49)."""

    matricula_id: int
    estudiante_id: int
    codigo: str
    nombres: str
    programa: str
    cohorte: str
    semestre: int
    clasificacion: str
    causa_codigo: Optional[str]
    causa_nombre: Optional[str]


@dataclass(frozen=True)
class Indicador:
    """Conteos e índice de no continuidad de un grupo (RF-50, RF-51)."""

    etiqueta: str
    inscritos: int
    graduados: int
    aplazados: int
    continuan: int
    no_continuan: int

    @property
    def base(self) -> int:
        """Inscritos sin graduados ni aplazados."""
        return self.inscritos - self.graduados - self.aplazados

    @property
    def indice(self) -> Optional[Decimal]:
        """Porcentaje de no continuidad (RF-50)."""
        return indice_no_continuidad(
            self.no_continuan, self.inscritos, self.graduados, self.aplazados
        )


def indice_no_continuidad(
    no_continuan: int, inscritos: int, graduados: int, aplazados: int
) -> Optional[Decimal]:
    """Índice de RF-50 en porcentaje; ``None`` si la base es 0.

    Ejemplo: 30 / (350 − 20 − 5) = 9,23 %.
    """
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-50
    return calculos.porcentaje(no_continuan, inscritos - graduados - aplazados)


def periodo_siguiente(periodo: PeriodoAcademico) -> Optional[PeriodoAcademico]:
    """Período que empieza inmediatamente después (RF-49)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-49
    return db.session.scalar(
        select(PeriodoAcademico)
        .where(PeriodoAcademico.fecha_inicio > periodo.fecha_inicio)
        .order_by(PeriodoAcademico.fecha_inicio)
        .limit(1)
    )


def periodos_evaluables() -> list[PeriodoAcademico]:
    """Períodos que tienen un período siguiente, del más reciente al más antiguo."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-49
    todos = list(
        db.session.scalars(
            select(PeriodoAcademico).order_by(PeriodoAcademico.fecha_inicio.desc())
        )
    )
    return todos[1:]


def _causa_vigente():
    """Subconsulta con la última causa registrada por matrícula (RF-52)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-52
    numerado = select(
        RegistroCausaNoContinuidad.matricula_periodo_id,
        RegistroCausaNoContinuidad.causa_no_continuidad_id,
        func.row_number()
        .over(
            partition_by=RegistroCausaNoContinuidad.matricula_periodo_id,
            order_by=RegistroCausaNoContinuidad.id.desc(),
        )
        .label("orden"),
    ).subquery()
    return (
        select(
            numerado.c.matricula_periodo_id,
            CausaNoContinuidad.codigo,
            CausaNoContinuidad.nombre,
        )
        .join(
            CausaNoContinuidad,
            CausaNoContinuidad.id == numerado.c.causa_no_continuidad_id,
        )
        .where(numerado.c.orden == 1)
        .subquery()
    )


def clasificar(periodo: PeriodoAcademico) -> list[FilaContinuidad]:
    """Clasifica a los inscritos del período frente al siguiente (RF-49).

    Raises:
        ErrorNegocio: el período no tiene un período siguiente registrado.
    """
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-49
    siguiente = periodo_siguiente(periodo)
    if siguiente is None:
        raise ErrorNegocio(
            f"El período {periodo.identificador} aún no tiene período siguiente: la "
            "continuidad se mide cuando exista."
        )
    estado = estudiantes.subconsulta_estado_vigente(siguiente.fecha_inicio)
    causa = _causa_vigente()
    en_siguiente = select(MatriculaPeriodo.estudiante_id).where(
        MatriculaPeriodo.periodo_academico_id == siguiente.id
    )
    consulta = (
        select(
            MatriculaPeriodo.id,
            Estudiante.id,
            Estudiante.codigo,
            Estudiante.nombres,
            ProgramaAcademico.nombre,
            Estudiante.periodo_ingreso,
            MatriculaPeriodo.semestre_cursado,
            estado.c.codigo,
            MatriculaPeriodo.estudiante_id.in_(en_siguiente),
            causa.c.codigo,
            causa.c.nombre,
        )
        .join(Estudiante, Estudiante.id == MatriculaPeriodo.estudiante_id)
        .join(
            ProgramaAcademico, ProgramaAcademico.id == Estudiante.programa_academico_id
        )
        .outerjoin(estado, estado.c.estudiante_id == Estudiante.id)
        .outerjoin(causa, causa.c.matricula_periodo_id == MatriculaPeriodo.id)
        .where(MatriculaPeriodo.periodo_academico_id == periodo.id)
        .order_by(Estudiante.nombres, Estudiante.codigo)
    )
    filas: list[FilaContinuidad] = []
    for (
        matricula_id,
        estudiante_id,
        codigo,
        nombres,
        programa,
        cohorte,
        semestre,
        estado_codigo,
        continua,
        causa_codigo,
        causa_nombre,
    ) in db.session.execute(consulta):
        if continua:
            clasificacion = CONTINUA
        elif estado_codigo == "graduado":
            clasificacion = GRADUADO
        elif estado_codigo == "aplazo_semestre":
            clasificacion = APLAZADO
        else:
            clasificacion = NO_CONTINUA
        filas.append(
            FilaContinuidad(
                matricula_id,
                estudiante_id,
                codigo,
                nombres,
                programa,
                cohorte,
                int(semestre),
                clasificacion,
                causa_codigo,
                causa_nombre,
            )
        )
    return filas


def indicador(etiqueta: str, filas: list[FilaContinuidad]) -> Indicador:
    """Conteos de un conjunto de filas de RF-49 (RF-50)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-50
    conteo = {clase: 0 for clase in NOMBRES_CLASIFICACION}
    for fila in filas:
        conteo[fila.clasificacion] += 1
    return Indicador(
        etiqueta,
        len(filas),
        conteo[GRADUADO],
        conteo[APLAZADO],
        conteo[CONTINUA],
        conteo[NO_CONTINUA],
    )


def por_grupo(
    filas: list[FilaContinuidad], clave: Callable[[FilaContinuidad], object]
) -> list[Indicador]:
    """Indicadores por cohorte o por semestre cursado (RF-51)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-51
    grupos: dict[object, list[FilaContinuidad]] = {}
    for fila in filas:
        grupos.setdefault(clave(fila), []).append(fila)
    return [indicador(str(k), grupos[k]) for k in sorted(grupos)]


def por_causa(filas: list[FilaContinuidad]) -> list[tuple[str, int]]:
    """Estudiantes que no continúan agrupados por causa y "sin causa" (RF-52)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-52
    conteo: dict[str, int] = {}
    for fila in filas:
        if fila.clasificacion == NO_CONTINUA:
            nombre = fila.causa_nombre or "Sin causa"
            conteo[nombre] = conteo.get(nombre, 0) + 1
    return sorted(conteo.items(), key=lambda par: (-par[1], par[0]))


def no_continuaron(
    filas: list[FilaContinuidad],
    programa: Optional[str] = None,
    semestre: Optional[int] = None,
    causa: Optional[str] = None,
) -> list[FilaContinuidad]:
    """Estudiantes que no continuaron, con filtros (RF-53)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-53
    resultado = [f for f in filas if f.clasificacion == NO_CONTINUA]
    if programa:
        resultado = [f for f in resultado if f.programa == programa]
    if semestre:
        resultado = [f for f in resultado if f.semestre == semestre]
    if causa == SIN_CAUSA:
        resultado = [f for f in resultado if f.causa_codigo is None]
    elif causa:
        resultado = [f for f in resultado if f.causa_codigo == causa]
    return resultado


def causas() -> list[CausaNoContinuidad]:
    """Lista fija de causas (RF-52)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-52
    return list(
        db.session.scalars(select(CausaNoContinuidad).order_by(CausaNoContinuidad.id))
    )


def registrar_causa(
    matricula_id: int, codigo_causa: str, actor_id: int
) -> RegistroCausaNoContinuidad:
    """Registra o cambia la causa de no continuidad, con historial (RF-52).

    Raises:
        ErrorNegocio: la matrícula no existe, el estudiante no está clasificado
            como "no continúa", la causa no es de la lista o no cambia.
    """
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-52
    try:
        matricula = db.session.get(MatriculaPeriodo, matricula_id)
        if matricula is None:
            raise ErrorNegocio("La matrícula no existe.")
        causa = db.session.scalar(
            select(CausaNoContinuidad).where(CausaNoContinuidad.codigo == codigo_causa)
        )
        if causa is None:
            raise ErrorNegocio("Seleccione una causa de la lista.")
        fila = next(
            (
                f
                for f in clasificar(matricula.periodo_academico)
                if f.matricula_id == matricula.id
            ),
            None,
        )
        if fila is None or fila.clasificacion != NO_CONTINUA:
            raise ErrorNegocio(
                "Solo se registra la causa de estudiantes que no continuaron."
            )
        if fila.causa_codigo == causa.codigo:
            raise ErrorNegocio("El estudiante ya tiene registrada esa causa.")
        registro = RegistroCausaNoContinuidad(
            matricula_periodo_id=matricula.id,
            causa_no_continuidad_id=causa.id,
            registrado_por_usuario_id=actor_id,
        )
        db.session.add(registro)
        db.session.flush()
        bitacora.registrar_evento(
            bitacora.EVENTO_CAMBIO_ADMINISTRATIVO,
            usuario_id=actor_id,
            entidad="registros_causa_no_continuidad",
            entidad_id=registro.id,
            detalle=(
                f"Causa de no continuidad «{causa.nombre}» para "
                f"{fila.codigo} en {matricula.periodo_academico.identificador}"
            ),
        )
        db.session.commit()
        return registro
    except Exception:
        db.session.rollback()
        raise


def historial_causas(matricula_ids: list[int]) -> dict[int, list[tuple]]:
    """Historial de causas por matrícula: (causa, usuario, fecha) (RF-52)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-52
    if not matricula_ids:
        return {}
    historial: dict[int, list[tuple]] = {}
    for matricula_id, nombre, usuario, fecha in db.session.execute(
        select(
            RegistroCausaNoContinuidad.matricula_periodo_id,
            CausaNoContinuidad.nombre,
            Usuario.nombre_completo,
            RegistroCausaNoContinuidad.registrado_en,
        )
        .join(CausaNoContinuidad)
        .join(
            Usuario, Usuario.id == RegistroCausaNoContinuidad.registrado_por_usuario_id
        )
        .where(RegistroCausaNoContinuidad.matricula_periodo_id.in_(matricula_ids))
        .order_by(RegistroCausaNoContinuidad.id.desc())
    ):
        historial.setdefault(matricula_id, []).append((nombre, usuario, fecha))
    return historial
