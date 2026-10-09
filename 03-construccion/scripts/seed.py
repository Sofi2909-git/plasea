"""Comando ``flask seed``: usuarios predeterminados y datos académicos mínimos.

Requiere haber ejecutado antes ``plasea_esquema.sql`` y ``bd_datos_iniciales.sql``
(roles, programa, estados, causas, eventos de bitácora y umbrales iniciales).

Es idempotente: cada registro se busca por su clave única antes de insertarlo, así
que puede ejecutarse varias veces sin duplicar datos ni cambiar contraseñas ya
existentes. Todos los datos son ficticios (RNF-07).

No genera sesiones de clase, asistencia, notas ni alertas: eso depende de RF-19,
RF-28, RF-29 y RF-40 a RF-43. El generador completo de 4 semestres es RF-25.

Uso (PowerShell, desde la raíz del repositorio)::

    flask seed
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import click
from flask.cli import with_appcontext
from sqlalchemy import func, select
from werkzeug.security import generate_password_hash

from plasea.modelos import (
    Asignatura,
    BloqueHorario,
    ConfiguracionAlerta,
    Corte,
    Curso,
    EstadoEstudiante,
    Estudiante,
    Festivo,
    HistorialEstadoEstudiante,
    Inscripcion,
    MatriculaPeriodo,
    PeriodoAcademico,
    ProgramaAcademico,
    Rol,
    Usuario,
    db,
)

PROGRAMA = "Ingeniería de Sistemas"

# (correo, contraseña, nombre completo, código de rol). Solo para el prototipo local.
USUARIOS_PREDETERMINADOS = (
    (
        "admin@plasea.edu.co",
        "Admin123*",
        "Administrador PLASEA",
        "administrador_sistema",
    ),
    (
        "auditor@plasea.edu.co",
        "Audit123*",
        "Auditor Académico PLASEA",
        "auditor_academico",
    ),
    ("profe1@plasea.edu.co", "Profe123*", "Profesor Uno PLASEA", "profesor"),
    ("profe2@plasea.edu.co", "Profe123*", "Profesor Dos PLASEA", "profesor"),
)

# Período en curso: 16 semanas desde el lunes 03/08/2026.
PERIODO = {
    "identificador": "2026-2",
    "fecha_inicio": dt.date(2026, 8, 3),
    "fecha_fin": dt.date(2026, 12, 2),
}

# (número, peso %, inicio, fin, límite de carga, límite de corrección)
CORTES = (
    (
        1,
        Decimal("30.00"),
        dt.date(2026, 8, 3),
        dt.date(2026, 9, 6),
        dt.date(2026, 9, 9),
        dt.date(2026, 9, 13),
    ),
    (
        2,
        Decimal("30.00"),
        dt.date(2026, 9, 7),
        dt.date(2026, 10, 11),
        dt.date(2026, 10, 14),
        dt.date(2026, 10, 18),
    ),
    (
        3,
        Decimal("40.00"),
        dt.date(2026, 10, 12),
        dt.date(2026, 11, 22),
        dt.date(2026, 11, 25),
        dt.date(2026, 11, 29),
    ),
)

# Festivos de Colombia dentro del período (Ley 51 de 1983).
FESTIVOS = (
    dt.date(2026, 8, 7),
    dt.date(2026, 8, 17),
    dt.date(2026, 10, 12),
    dt.date(2026, 11, 2),
    dt.date(2026, 11, 16),
)

# (código, nombre, créditos, horas semanales, nivel)
ASIGNATURAS = (
    ("ISI501", "Ingeniería de Software I", 4, 4, 5),
    ("ISI602", "Bases de Datos II", 3, 3, 6),
)

# (código asignatura, código curso, correo profesor, bloques (día ISO, inicio, fin))
CURSOS = (
    (
        "ISI501",
        "T01",
        "profe1@plasea.edu.co",
        ((1, dt.time(7, 0), dt.time(9, 0)), (3, dt.time(7, 0), dt.time(9, 0))),
    ),
    ("ISI602", "T01", "profe2@plasea.edu.co", ((4, dt.time(14, 0), dt.time(17, 0)),)),
)

# (código, nombres, correo, período de ingreso, semestre cursado en 2026-2)
ESTUDIANTES = (
    (
        "20231001",
        "Laura Camila Rojas Peña",
        "est01@estudiantes.plasea.edu.co",
        "2024-1",
        6,
    ),
    (
        "20231002",
        "Juan David Torres Mora",
        "est02@estudiantes.plasea.edu.co",
        "2024-1",
        6,
    ),
    (
        "20231003",
        "María Fernanda Ortiz León",
        "est03@estudiantes.plasea.edu.co",
        "2024-1",
        6,
    ),
    (
        "20231004",
        "Carlos Andrés Vera Díaz",
        "est04@estudiantes.plasea.edu.co",
        "2024-1",
        6,
    ),
    (
        "20231005",
        "Valentina Suárez Gómez",
        "est05@estudiantes.plasea.edu.co",
        "2023-2",
        7,
    ),
    ("20231006", "Santiago Pabón Ruiz", "est06@estudiantes.plasea.edu.co", "2023-2", 7),
    (
        "20231007",
        "Daniela Contreras Jaimes",
        "est07@estudiantes.plasea.edu.co",
        "2024-2",
        5,
    ),
    (
        "20231008",
        "Andrés Felipe Quintero Celis",
        "est08@estudiantes.plasea.edu.co",
        "2024-2",
        5,
    ),
)


class ErrorSeed(Exception):
    """Error controlado durante la carga de datos predeterminados."""


@click.command("seed")
@with_appcontext
def comando_seed() -> None:
    """Crea los 4 usuarios predeterminados y los datos académicos mínimos."""
    # Responsable: Islender Arturo Alfonso
    # RF-25
    try:
        resumen = ejecutar_seed()
        db.session.commit()
    except ErrorSeed as error:
        db.session.rollback()
        raise click.ClickException(str(error)) from error
    except Exception:
        db.session.rollback()
        raise
    for entidad, cantidad in resumen.items():
        click.echo(f"{entidad}: {cantidad} nuevos")
    click.echo("Seed completado.")


def ejecutar_seed() -> dict[str, int]:
    """Inserta los datos que falten y devuelve cuántos registros nuevos hubo."""
    # Responsable: Islender Arturo Alfonso
    # RF-25
    _verificar_datos_iniciales()
    resumen = {
        "Usuarios": _crear_usuarios(),
    }
    periodo, nuevo_periodo = _obtener_o_crear_periodo()
    resumen["Períodos"] = int(nuevo_periodo)
    resumen["Cortes"] = _crear_cortes(periodo)
    resumen["Festivos"] = _crear_festivos(periodo)
    resumen["Asignaturas"] = _crear_asignaturas()
    resumen["Cursos"], resumen["Bloques de horario"] = _crear_cursos(periodo)
    resumen["Estudiantes"] = _crear_estudiantes()
    resumen["Matrículas"], resumen["Inscripciones"] = _crear_inscripciones(periodo)
    return resumen


def _verificar_datos_iniciales() -> None:
    """Comprueba que bd_datos_iniciales.sql ya se ejecutó."""
    # Responsable: Islender Arturo Alfonso
    # RF-25
    codigos_rol = {fila[3] for fila in USUARIOS_PREDETERMINADOS}
    existentes = set(
        db.session.scalars(select(Rol.codigo).where(Rol.codigo.in_(codigos_rol)))
    )
    faltantes = []
    if existentes != codigos_rol:
        faltantes.append("roles")
    if _programa() is None:
        faltantes.append("programa académico")
    if _estado_activo() is None:
        faltantes.append("estados del estudiante")
    if db.session.scalar(select(func.count(ConfiguracionAlerta.id))) == 0:
        faltantes.append("configuración de alertas")
    if faltantes:
        raise ErrorSeed(
            "Faltan datos iniciales (" + ", ".join(faltantes) + "). Ejecute "
            "03-construccion/scripts/bd_datos_iniciales.sql antes de 'flask seed'."
        )


def _programa() -> ProgramaAcademico | None:
    """Devuelve el programa académico del alcance."""
    # Responsable: Islender Arturo Alfonso
    # RF-25
    return db.session.scalar(
        select(ProgramaAcademico).where(ProgramaAcademico.nombre == PROGRAMA)
    )


def _estado_activo() -> EstadoEstudiante | None:
    """Devuelve el estado 'activo' del catálogo."""
    # Responsable: Islender Arturo Alfonso
    # RF-25
    return db.session.scalar(
        select(EstadoEstudiante).where(EstadoEstudiante.codigo == "activo")
    )


def _usuario_por_correo(correo: str) -> Usuario | None:
    """Busca un usuario por correo sin distinguir mayúsculas."""
    # Responsable: Islender Arturo Alfonso
    # RF-25
    return db.session.scalar(
        select(Usuario).where(func.lower(Usuario.correo) == correo.lower())
    )


def _crear_usuarios() -> int:
    """Crea los 4 usuarios predeterminados si no existen (cuentas activas)."""
    # Responsable: Islender Arturo Alfonso
    # RF-25
    roles = {rol.codigo: rol for rol in db.session.scalars(select(Rol))}
    nuevos = 0
    for correo, contrasena, nombre, codigo_rol in USUARIOS_PREDETERMINADOS:
        if _usuario_por_correo(correo) is not None:
            continue
        db.session.add(
            Usuario(
                nombre_completo=nombre,
                correo=correo,
                contrasena_hash=generate_password_hash(contrasena),
                rol=roles[codigo_rol],
                estado_cuenta="activa",
                intentos_fallidos=0,
            )
        )
        nuevos += 1
    db.session.flush()
    return nuevos


def _obtener_o_crear_periodo() -> tuple[PeriodoAcademico, bool]:
    """Obtiene o crea el período 2026-2; lo marca en curso si no hay otro."""
    # Responsable: Islender Arturo Alfonso
    # RF-25
    periodo = db.session.scalar(
        select(PeriodoAcademico).where(
            PeriodoAcademico.identificador == PERIODO["identificador"]
        )
    )
    if periodo is not None:
        return periodo, False
    hay_en_curso = db.session.scalar(
        select(func.count(PeriodoAcademico.id)).where(
            PeriodoAcademico.en_curso_marca == 1
        )
    )
    periodo = PeriodoAcademico(**PERIODO, en_curso_marca=None if hay_en_curso else 1)
    db.session.add(periodo)
    db.session.flush()
    return periodo, True


def _crear_cortes(periodo: PeriodoAcademico) -> int:
    """Crea los 3 cortes del período (30 %, 30 % y 40 %)."""
    # Responsable: Islender Arturo Alfonso
    # RF-25
    existentes = {corte.numero for corte in periodo.cortes}
    nuevos = 0
    for numero, peso, inicio, fin, limite_carga, limite_correccion in CORTES:
        if numero in existentes:
            continue
        db.session.add(
            Corte(
                periodo_academico=periodo,
                numero=numero,
                peso_porcentaje=peso,
                fecha_inicio=inicio,
                fecha_fin=fin,
                limite_carga=limite_carga,
                limite_correccion=limite_correccion,
            )
        )
        nuevos += 1
    db.session.flush()
    return nuevos


def _crear_festivos(periodo: PeriodoAcademico) -> int:
    """Registra los festivos del período."""
    # Responsable: Islender Arturo Alfonso
    # RF-25
    existentes = {festivo.fecha for festivo in periodo.festivos}
    nuevos = 0
    for fecha in FESTIVOS:
        if fecha in existentes:
            continue
        db.session.add(Festivo(periodo_academico=periodo, fecha=fecha))
        nuevos += 1
    db.session.flush()
    return nuevos


def _crear_asignaturas() -> int:
    """Crea las asignaturas mínimas del programa."""
    # Responsable: Islender Arturo Alfonso
    # RF-25
    programa = _programa()
    nuevos = 0
    for codigo, nombre, creditos, horas, nivel in ASIGNATURAS:
        existe = db.session.scalar(
            select(Asignatura.id).where(Asignatura.codigo == codigo)
        )
        if existe is not None:
            continue
        db.session.add(
            Asignatura(
                codigo=codigo,
                nombre=nombre,
                programa_academico=programa,
                creditos=creditos,
                horas_semanales=horas,
                nivel=nivel,
            )
        )
        nuevos += 1
    db.session.flush()
    return nuevos


def _crear_cursos(periodo: PeriodoAcademico) -> tuple[int, int]:
    """Crea un curso por asignatura con su profesor y su horario semanal."""
    # Responsable: Islender Arturo Alfonso
    # RF-25
    cursos_nuevos = 0
    bloques_nuevos = 0
    for codigo_asignatura, codigo_curso, correo_profesor, bloques in CURSOS:
        asignatura = db.session.scalar(
            select(Asignatura).where(Asignatura.codigo == codigo_asignatura)
        )
        curso = db.session.scalar(
            select(Curso).where(
                Curso.asignatura_id == asignatura.id,
                Curso.periodo_academico_id == periodo.id,
                Curso.codigo == codigo_curso,
            )
        )
        if curso is None:
            curso = Curso(
                asignatura=asignatura,
                periodo_academico=periodo,
                codigo=codigo_curso,
                profesor=_usuario_por_correo(correo_profesor),
            )
            db.session.add(curso)
            db.session.flush()
            cursos_nuevos += 1
        existentes = {(b.dia_semana, b.hora_inicio) for b in curso.bloques_horario}
        for dia, inicio, fin in bloques:
            if (dia, inicio) in existentes:
                continue
            db.session.add(
                BloqueHorario(
                    curso=curso, dia_semana=dia, hora_inicio=inicio, hora_fin=fin
                )
            )
            bloques_nuevos += 1
    db.session.flush()
    return cursos_nuevos, bloques_nuevos


def _crear_estudiantes() -> int:
    """Crea los estudiantes ficticios con su estado inicial 'activo'."""
    # Responsable: Islender Arturo Alfonso
    # RF-25
    programa = _programa()
    activo = _estado_activo()
    auditor = _usuario_por_correo("auditor@plasea.edu.co")
    nuevos = 0
    for codigo, nombres, correo, ingreso, _semestre in ESTUDIANTES:
        existe = db.session.scalar(
            select(Estudiante.id).where(Estudiante.codigo == codigo)
        )
        if existe is not None:
            continue
        estudiante = Estudiante(
            codigo=codigo,
            nombres=nombres,
            correo=correo,
            programa_academico=programa,
            periodo_ingreso=ingreso,
        )
        db.session.add(estudiante)
        db.session.add(
            HistorialEstadoEstudiante(
                estudiante=estudiante,
                estado_estudiante=activo,
                fecha_efectiva=_fecha_inicio_cohorte(ingreso),
                registrado_por=auditor,
            )
        )
        nuevos += 1
    db.session.flush()
    return nuevos


def _fecha_inicio_cohorte(periodo_ingreso: str) -> dt.date:
    """Fecha efectiva del estado inicial: 1 de febrero o 1 de agosto del ingreso."""
    # Responsable: Islender Arturo Alfonso
    # RF-25
    anio, semestre = periodo_ingreso.split("-")
    return dt.date(int(anio), 2 if semestre == "1" else 8, 1)


def _crear_inscripciones(periodo: PeriodoAcademico) -> tuple[int, int]:
    """Matricula a los estudiantes en el período y los inscribe en todos los cursos."""
    # Responsable: Islender Arturo Alfonso
    # RF-25
    cursos = list(
        db.session.scalars(
            select(Curso).where(Curso.periodo_academico_id == periodo.id)
        )
    )
    matriculas_nuevas = 0
    inscripciones_nuevas = 0
    for codigo, _nombres, _correo, _ingreso, semestre in ESTUDIANTES:
        estudiante = db.session.scalar(
            select(Estudiante).where(Estudiante.codigo == codigo)
        )
        matricula = db.session.scalar(
            select(MatriculaPeriodo).where(
                MatriculaPeriodo.estudiante_id == estudiante.id,
                MatriculaPeriodo.periodo_academico_id == periodo.id,
            )
        )
        if matricula is None:
            matricula = MatriculaPeriodo(
                estudiante=estudiante,
                periodo_academico=periodo,
                semestre_cursado=semestre,
            )
            db.session.add(matricula)
            db.session.flush()
            matriculas_nuevas += 1
        inscritos = {inscripcion.curso_id for inscripcion in matricula.inscripciones}
        for curso in cursos:
            if curso.id in inscritos:
                continue
            db.session.add(
                Inscripcion(
                    matricula_periodo_id=matricula.id,
                    curso_id=curso.id,
                    periodo_academico_id=periodo.id,
                )
            )
            inscripciones_nuevas += 1
    db.session.flush()
    return matriculas_nuevas, inscripciones_nuevas
