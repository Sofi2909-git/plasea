"""Generador de datos de prueba coherentes de 4 semestres (RF-25).

Lo ejecuta el Administrador del sistema con ``flask generar-datos-prueba``.
Todos los datos son ficticios (RNF-07) y repetibles con la misma semilla.

Genera, para 2025-1, 2025-2, 2026-1 y 2026-2: períodos de 16 semanas con sus
3 cortes y festivos de Colombia, 25 asignaturas, 50 cursos por período con
horario y calendario de sesiones, unos 900 estudiantes con historial de
estados, matrículas, inscripciones, asistencia (solo ausentes) y notas. El
estado de cada corte depende de la fecha actual: los cortes vencidos quedan
cerrados y enviados, el corte en curso queda con borradores parciales.

No genera alertas (RF-40 a RF-43): se calculan con los datos generados.

Inserta por lotes (``insert`` con muchas filas) y recupera los identificadores
con una consulta por tabla, así que el tiempo no crece con una consulta por fila.
"""

from __future__ import annotations

import datetime as dt
import random
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Optional

from sqlalchemy import bindparam, delete, func, insert, select
from werkzeug.security import generate_password_hash

from plasea.modelos import (
    Alerta,
    Asignatura,
    Ausencia,
    BloqueHorario,
    ConfiguracionAlerta,
    Corte,
    Curso,
    EstadoEstudiante,
    Estudiante,
    Festivo,
    HistorialAusencia,
    HistorialEstadoEstudiante,
    HistorialNota,
    Inscripcion,
    MatriculaPeriodo,
    NotaCorte,
    PeriodoAcademico,
    ProgramaAcademico,
    ReaperturaCurso,
    RegistroCausaNoContinuidad,
    RegistroCursoCorte,
    Rol,
    SesionClase,
    Usuario,
    db,
)
from plasea.servicios import bitacora, calendario, periodos
from plasea.servicios.comunes import ErrorNegocio, ahora
from plasea.servicios.cuentas import ROL_ADMINISTRADOR, ROL_PROFESOR

PROGRAMA = "Ingeniería de Sistemas"
CONTRASENA_PROFESORES = "Profe123*"  # Solo prototipo local con datos ficticios.
DOMINIO_ESTUDIANTES = "estudiantes.plasea.edu.co"

# (identificador, inicio lunes, fin domingo de la semana 16)
PERIODOS = (
    ("2025-1", dt.date(2025, 2, 3), dt.date(2025, 5, 25)),
    ("2025-2", dt.date(2025, 8, 4), dt.date(2025, 11, 23)),
    ("2026-1", dt.date(2026, 2, 2), dt.date(2026, 5, 24)),
    ("2026-2", dt.date(2026, 8, 3), dt.date(2026, 11, 22)),
)

# Festivos de Colombia (Ley 51 de 1983) dentro de cada período.
FESTIVOS = {
    "2025-1": ("2025-03-24", "2025-04-17", "2025-04-18", "2025-05-01"),
    "2025-2": ("2025-08-07", "2025-08-18", "2025-10-13", "2025-11-03", "2025-11-17"),
    "2026-1": ("2026-03-23", "2026-04-02", "2026-04-03", "2026-05-01", "2026-05-18"),
    "2026-2": ("2026-08-07", "2026-08-17", "2026-10-12", "2026-11-02", "2026-11-16"),
}

# (código, nombre, créditos, horas semanales, nivel): 25 asignaturas.
ASIGNATURAS = (
    ("ISI101", "Fundamentos de Programación", 4, 4, 1),
    ("ISI102", "Cálculo Diferencial", 4, 4, 1),
    ("ISI103", "Introducción a la Ingeniería de Sistemas", 3, 3, 1),
    ("ISI201", "Programación Orientada a Objetos", 4, 4, 2),
    ("ISI202", "Cálculo Integral", 4, 4, 2),
    ("ISI203", "Matemáticas Discretas", 3, 3, 2),
    ("ISI301", "Estructuras de Datos", 4, 4, 3),
    ("ISI302", "Álgebra Lineal", 3, 3, 3),
    ("ISI303", "Física Mecánica", 4, 4, 3),
    ("ISI401", "Bases de Datos I", 4, 4, 4),
    ("ISI402", "Análisis Numérico", 3, 3, 4),
    ("ISI403", "Arquitectura de Computadores", 3, 3, 4),
    ("ISI501", "Ingeniería de Software I", 4, 4, 5),
    ("ISI502", "Sistemas Operativos", 3, 3, 5),
    ("ISI503", "Probabilidad y Estadística", 3, 3, 5),
    ("ISI601", "Ingeniería de Software II", 4, 4, 6),
    ("ISI602", "Bases de Datos II", 3, 3, 6),
    ("ISI701", "Redes de Computadores", 4, 4, 7),
    ("ISI702", "Inteligencia Artificial", 3, 3, 7),
    ("ISI801", "Gestión de Proyectos", 3, 3, 8),
    ("ISI802", "Seguridad Informática", 3, 3, 8),
    ("ISI901", "Computación en la Nube", 3, 3, 9),
    ("ISI902", "Auditoría de Sistemas", 3, 3, 9),
    ("ISI1001", "Trabajo de Grado", 4, 4, 10),
    ("ISI1002", "Ética Profesional", 3, 3, 10),
)
CURSOS_POR_ASIGNATURA = ("T01", "T02")

PROFESORES_SEED = ("profe1@plasea.edu.co", "profe2@plasea.edu.co")
PROFESORES_GENERADOS = (
    "Marta Lucía Ramírez Ortega",
    "Hernán Darío Castellanos Rincón",
    "Claudia Patricia Villamizar Duarte",
    "Jorge Enrique Peñaranda Gélvez",
    "Diana Carolina Bautista Contreras",
    "Óscar Javier Sandoval Parada",
    "Liliana Andrea Jaimes Carrillo",
    "Fredy Alberto Quintero Mantilla",
    "Sandra Milena Ortiz Lozano",
    "Ricardo Antonio Durán Suárez",
)

NOMBRES = (
    "Valentina",
    "Santiago",
    "Daniela",
    "Sebastián",
    "Mariana",
    "Juan Pablo",
    "Laura",
    "Andrés",
    "Camila",
    "Nicolás",
    "Paula",
    "Mateo",
    "Sofía",
    "Samuel",
    "Isabella",
    "Julián",
    "Gabriela",
    "Felipe",
    "Natalia",
    "David",
    "Juliana",
    "Esteban",
    "Manuela",
    "Alejandro",
    "Sara",
    "Diego",
    "Luisa Fernanda",
    "Miguel Ángel",
    "Ana María",
    "Carlos Eduardo",
    "María José",
    "Kevin",
    "Yuliana",
    "Brayan",
    "Karen",
    "Jhon Fredy",
    "Angie",
    "Cristian",
    "Lina",
    "Óscar",
)
APELLIDOS = (
    "Rojas",
    "Contreras",
    "Jaimes",
    "Peñaranda",
    "Villamizar",
    "Gélvez",
    "Ortiz",
    "Suárez",
    "Duarte",
    "Carrillo",
    "Mantilla",
    "Rincón",
    "Parada",
    "Sandoval",
    "Bautista",
    "Quintero",
    "Lozano",
    "Durán",
    "Ramírez",
    "Celis",
    "Pabón",
    "Moreno",
    "Galvis",
    "Ardila",
    "Becerra",
    "Cáceres",
    "Delgado",
    "Fuentes",
    "Guerrero",
    "Hernández",
    "Ibáñez",
    "León",
    "Medina",
    "Niño",
    "Ochoa",
    "Pérez",
    "Rangel",
    "Torres",
    "Uribe",
    "Vera",
)

# Horas de inicio posibles para los bloques (07:00 a 20:00).
HORAS_INICIO = (7, 9, 11, 14, 16, 18)
PATRONES_4H = ((1, 3), (2, 4), (3, 5), (1, 4))
PATRONES_3H = ((5,), (2,), (4,), (6,))


@dataclass(frozen=True)
class Volumen:
    """Tamaño de los datos (por defecto, el de RF-25 y la sección 7)."""

    estudiantes_iniciales: int = 350
    nuevos_por_periodo: int = 60
    historicos: int = 370


@dataclass
class _Estudiante:
    """Estado de simulación de un estudiante."""

    codigo: str
    nombres: str
    cohorte: str
    semestre: int
    activo: bool = True
    aplazado_hasta: Optional[int] = None
    id: Optional[int] = None


def _ordinal(identificador: str) -> int:
    """Convierte AAAA-S en un número consecutivo de semestre."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-25
    anio, semestre = identificador.split("-")
    return int(anio) * 2 + int(semestre) - 1


def _identificador(ordinal: int) -> str:
    """Inverso de ``_ordinal``."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-25
    return f"{ordinal // 2}-{ordinal % 2 + 1}"


def _inicio_cohorte(cohorte: str) -> dt.date:
    """Fecha aproximada de inicio de una cohorte (1 de febrero o de agosto)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-25
    anio, semestre = cohorte.split("-")
    return dt.date(int(anio), 2 if semestre == "1" else 8, 1)


def _nota(aleatorio: random.Random, media: float) -> Decimal:
    """Nota de corte entre 1,0 y 5,0 con un decimal."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-25
    valor = min(5.0, max(1.0, aleatorio.gauss(media, 0.45)))
    return Decimal(f"{valor:.1f}")


def _insertar(modelo: type, filas: list[dict]) -> None:
    """Inserción por lotes con el ORM (una sentencia ``executemany``)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-25
    for inicio in range(0, len(filas), 5000):
        db.session.execute(insert(modelo), filas[inicio : inicio + 5000])


def _reiniciar() -> None:
    """Borra los datos académicos de prueba conservando cuentas y catálogos.

    Raises:
        ErrorNegocio: existe historial de correcciones (solo inserción en la BD).
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-25
    historial = db.session.scalar(select(func.count(HistorialNota.id))) or 0
    historial += db.session.scalar(select(func.count(HistorialAusencia.id))) or 0
    if historial:
        raise ErrorNegocio(
            "Hay historial de correcciones, que la base de datos protege como de solo "
            "inserción. Para regenerar, vuelva a crear la base con los scripts de "
            "esquema y datos iniciales."
        )
    for modelo in (
        Alerta,
        RegistroCausaNoContinuidad,
        ReaperturaCurso,
        Ausencia,
        NotaCorte,
        RegistroCursoCorte,
        Inscripcion,
        MatriculaPeriodo,
        HistorialEstadoEstudiante,
        Estudiante,
        SesionClase,
        BloqueHorario,
        Curso,
        Festivo,
        Corte,
        PeriodoAcademico,
        Asignatura,
    ):
        db.session.execute(delete(modelo))
    db.session.flush()


def _profesores(buzones: list[str]) -> list[int]:
    """Obtiene o crea las cuentas de profesor (idempotente por correo)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-25
    rol_id = db.session.scalar(select(Rol.id).where(Rol.codigo == ROL_PROFESOR))
    correos = list(PROFESORES_SEED) + [
        buzones[i] if i < len(buzones) else f"docente{i + 3:02d}@plasea.edu.co"
        for i in range(len(PROFESORES_GENERADOS))
    ]
    nombres = ["Profesor Uno PLASEA", "Profesor Dos PLASEA", *PROFESORES_GENERADOS]
    existentes = {
        u.correo.lower(): u
        for u in db.session.scalars(
            select(Usuario).where(
                func.lower(Usuario.correo).in_([c.lower() for c in correos])
            )
        )
    }
    clave = generate_password_hash(CONTRASENA_PROFESORES)
    ids: list[int] = []
    for correo, nombre in zip(correos, nombres):
        usuario = existentes.get(correo.lower())
        if usuario is None:
            usuario = Usuario(
                nombre_completo=nombre,
                correo=correo.lower(),
                contrasena_hash=clave,
                rol_id=rol_id,
                estado_cuenta="activa",
                intentos_fallidos=0,
            )
            db.session.add(usuario)
            db.session.flush()
        elif usuario.rol_id != rol_id:
            raise ErrorNegocio(f"La cuenta {correo} existe y no tiene rol Profesor.")
        ids.append(usuario.id)
    return ids


def _bloques(
    aleatorio: random.Random,
    horas: int,
    ocupado: set[tuple[int, int, int]],
    profesor_id: int,
) -> list[tuple[int, dt.time, dt.time]]:
    """Horario semanal del curso sin cruces para el profesor."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-25
    patrones = list(PATRONES_4H if horas == 4 else PATRONES_3H)
    duracion = 2 if horas == 4 else 3
    candidatos = [(p, h) for p in patrones for h in HORAS_INICIO if h + duracion <= 21]
    aleatorio.shuffle(candidatos)
    for dias, hora in candidatos:
        celdas = {(profesor_id, dia, hora + i) for dia in dias for i in range(duracion)}
        if not celdas & ocupado:
            ocupado.update(celdas)
            return [(dia, dt.time(hora), dt.time(hora + duracion)) for dia in dias]
    raise ErrorNegocio("No se encontró un horario libre para un profesor.")


def generar(
    correo_administrador: str,
    reiniciar: bool = False,
    semilla: int = 2026,
    buzones: Optional[list[str]] = None,
    volumen: Volumen = Volumen(),
    avisar: Callable[[str], None] = lambda _texto: None,
) -> dict[str, int]:
    """Genera los datos de prueba de 4 semestres en una sola transacción (RF-25).

    Args:
        correo_administrador: cuenta activa de Administrador del sistema que
            queda como responsable de los registros de estado.
        reiniciar: borra antes los datos académicos (las cuentas se conservan).
        semilla: hace la generación repetible.
        buzones: correos reales del equipo para los primeros profesores
            generados (el resto de cuentas usa correos ficticios).
        volumen: tamaño de los datos (las pruebas usan uno reducido).
        avisar: función para informar el avance.

    Returns:
        Cantidad de registros generados por entidad.

    Raises:
        ErrorNegocio: administrador inválido, faltan catálogos o ya hay datos
            académicos sin ``reiniciar``.
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-25
    try:
        administrador = db.session.scalar(
            select(Usuario)
            .join(Rol, Rol.id == Usuario.rol_id)
            .where(
                func.lower(Usuario.correo) == correo_administrador.strip().lower(),
                Rol.codigo == ROL_ADMINISTRADOR,
                Usuario.estado_cuenta == "activa",
            )
        )
        if administrador is None:
            raise ErrorNegocio(
                "Indique el correo de una cuenta activa de Administrador del sistema."
            )
        programa_id = db.session.scalar(
            select(ProgramaAcademico.id).where(ProgramaAcademico.nombre == PROGRAMA)
        )
        estados = {e.codigo: e.id for e in db.session.scalars(select(EstadoEstudiante))}
        faltan = {
            "activo",
            "graduado",
            "retirado_formal",
            "aplazo_semestre",
            "cancelado",
        }
        if programa_id is None or not faltan <= estados.keys():
            raise ErrorNegocio(
                "Faltan datos iniciales (programa o estados del estudiante). Ejecute "
                "primero los scripts de datos iniciales."
            )
        if reiniciar:
            avisar("Borrando datos académicos anteriores...")
            _reiniciar()
        elif any(
            db.session.scalar(select(func.count(modelo.id)))
            for modelo in (PeriodoAcademico, Estudiante, Asignatura)
        ):
            raise ErrorNegocio(
                "Ya hay datos académicos. Use --reiniciar para borrarlos y regenerar."
            )
        if not db.session.scalar(select(func.count(ConfiguracionAlerta.id))):
            db.session.add(ConfiguracionAlerta(creado_por_usuario_id=administrador.id))

        aleatorio = random.Random(semilla)
        hoy = ahora().date()
        resumen: dict[str, int] = {}
        profesores = _profesores(buzones or [])
        resumen["Profesores disponibles"] = len(profesores)

        # --- Asignaturas -----------------------------------------------------
        _insertar(
            Asignatura,
            [
                {
                    "codigo": codigo,
                    "nombre": nombre,
                    "programa_academico_id": programa_id,
                    "creditos": creditos,
                    "horas_semanales": horas,
                    "nivel": nivel,
                }
                for codigo, nombre, creditos, horas, nivel in ASIGNATURAS
            ],
        )
        asignaturas = {a.codigo: a for a in db.session.scalars(select(Asignatura))}
        por_nivel: dict[int, list[Asignatura]] = {}
        for asignatura in asignaturas.values():
            por_nivel.setdefault(asignatura.nivel, []).append(asignatura)
        resumen["Asignaturas"] = len(asignaturas)

        # --- Períodos, cortes y festivos --------------------------------------
        objetos_periodo: list[PeriodoAcademico] = []
        for identificador, inicio, fin in PERIODOS:
            periodo = PeriodoAcademico(
                identificador=identificador, fecha_inicio=inicio, fecha_fin=fin
            )
            db.session.add(periodo)
            objetos_periodo.append(periodo)
        db.session.flush()
        en_curso = next(
            (p for p in objetos_periodo if p.fecha_inicio <= hoy <= p.fecha_fin),
            max(
                (p for p in objetos_periodo if p.fecha_inicio <= hoy),
                key=lambda p: p.fecha_inicio,
                default=objetos_periodo[0],
            ),
        )
        db.session.execute(
            PeriodoAcademico.__table__.update()
            .where(PeriodoAcademico.en_curso_marca == 1)
            .values(en_curso_marca=None)
        )
        en_curso.en_curso_marca = 1
        cortes_por_periodo: dict[int, list[Corte]] = {}
        for periodo in objetos_periodo:
            lista = []
            for datos in periodos.cortes_sugeridos(periodo):
                cerrado = hoy > datos.limite_correccion
                corte = Corte(
                    periodo_academico_id=periodo.id,
                    **datos.__dict__,
                    cerrado_en=(
                        dt.datetime.combine(
                            datos.limite_correccion + dt.timedelta(days=1), dt.time()
                        )
                        if cerrado
                        else None
                    ),
                    tipo_cierre="automatico" if cerrado else None,
                    # El resumen de RF-57 de los cortes históricos se da por enviado.
                    aviso_resumen_enviado_en=(
                        dt.datetime.combine(
                            datos.limite_correccion + dt.timedelta(days=1), dt.time()
                        )
                        if cerrado
                        else None
                    ),
                )
                db.session.add(corte)
                lista.append(corte)
            cortes_por_periodo[periodo.id] = lista
            db.session.add_all(
                Festivo(periodo_academico_id=periodo.id, fecha=dt.date.fromisoformat(f))
                for f in FESTIVOS[periodo.identificador]
            )
        db.session.flush()
        resumen["Períodos"] = len(objetos_periodo)
        resumen["Cortes"] = sum(len(c) for c in cortes_por_periodo.values())

        # --- Cursos, horarios y sesiones --------------------------------------
        avisar("Generando cursos, horarios y calendarios...")
        cursos_periodo: dict[int, list[tuple[Curso, Asignatura]]] = {}
        bloques_filas: list[dict] = []
        sesiones_filas: list[dict] = []
        for periodo in objetos_periodo:
            ocupado: set[tuple[int, int, int]] = set()
            festivos = [
                dt.date.fromisoformat(f) for f in FESTIVOS[periodo.identificador]
            ]
            lista_cursos: list[tuple[Curso, Asignatura]] = []
            turno = 0
            for asignatura in sorted(asignaturas.values(), key=lambda a: a.codigo):
                for codigo_curso in CURSOS_POR_ASIGNATURA:
                    # Los profesores del seed conservan ISI501 T01 e ISI602 T01.
                    if asignatura.codigo == "ISI501" and codigo_curso == "T01":
                        profesor_id = profesores[0]
                    elif asignatura.codigo == "ISI602" and codigo_curso == "T01":
                        profesor_id = profesores[1]
                    else:
                        profesor_id = profesores[turno % len(profesores)]
                        turno += 1
                    curso = Curso(
                        asignatura_id=asignatura.id,
                        periodo_academico_id=periodo.id,
                        codigo=codigo_curso,
                        profesor_usuario_id=profesor_id,
                    )
                    db.session.add(curso)
                    lista_cursos.append((curso, asignatura))
            db.session.flush()
            for curso, asignatura in lista_cursos:
                bloques = _bloques(
                    aleatorio,
                    asignatura.horas_semanales,
                    ocupado,
                    curso.profesor_usuario_id,
                )
                bloques_filas.extend(
                    {
                        "curso_id": curso.id,
                        "dia_semana": dia,
                        "hora_inicio": inicio,
                        "hora_fin": fin,
                    }
                    for dia, inicio, fin in bloques
                )
                sesiones_filas.extend(
                    {
                        "curso_id": curso.id,
                        "fecha": sesion.fecha,
                        "hora_inicio": sesion.hora_inicio,
                        "hora_fin": sesion.hora_fin,
                    }
                    for sesion in calendario.calcular_sesiones(
                        bloques, periodo.fecha_inicio, periodo.fecha_fin, festivos
                    )
                )
            cursos_periodo[periodo.id] = lista_cursos
        _insertar(BloqueHorario, bloques_filas)
        _insertar(SesionClase, sesiones_filas)
        resumen["Cursos"] = sum(len(c) for c in cursos_periodo.values())
        resumen["Sesiones de clase"] = len(sesiones_filas)

        # --- Estudiantes: población y trayectoria -----------------------------
        avisar("Simulando estudiantes, estados y matrículas...")
        usados: set[str] = set()

        def nombre_aleatorio() -> str:
            # Responsable: Yeferson Fabián Jaimes
            # RF-25
            while True:
                nombre = (
                    f"{aleatorio.choice(NOMBRES)} {aleatorio.choice(APELLIDOS)} "
                    f"{aleatorio.choice(APELLIDOS)}"
                )
                if nombre not in usados:
                    usados.add(nombre)
                    return nombre

        consecutivos: dict[str, int] = {}

        def codigo_para(cohorte: str) -> str:
            # Responsable: Yeferson Fabián Jaimes
            # RF-25
            consecutivos[cohorte] = consecutivos.get(cohorte, 0) + 1
            return f"{cohorte.replace('-', '')}{consecutivos[cohorte]:03d}"

        poblacion: list[_Estudiante] = []
        estados_filas: list[tuple[str, str, dt.date]] = []
        primer = _ordinal(PERIODOS[0][0])
        pesos = [48, 44, 40, 37, 35, 33, 31, 29, 27, 26]
        total_pesos = sum(pesos)
        for semestre, peso in enumerate(pesos, start=1):
            cantidad = round(volumen.estudiantes_iniciales * peso / total_pesos)
            for _ in range(cantidad):
                cohorte = _identificador(primer - (semestre - 1))
                estudiante = _Estudiante(
                    codigo_para(cohorte), nombre_aleatorio(), cohorte, semestre
                )
                poblacion.append(estudiante)
                estados_filas.append(
                    (estudiante.codigo, "activo", _inicio_cohorte(cohorte))
                )
        historicos: list[_Estudiante] = []
        for _ in range(volumen.historicos):
            cohorte = _identificador(primer - aleatorio.randint(10, 20))
            estudiante = _Estudiante(
                codigo_para(cohorte), nombre_aleatorio(), cohorte, 10, False
            )
            historicos.append(estudiante)
            inicio = _inicio_cohorte(cohorte)
            estados_filas.append((estudiante.codigo, "activo", inicio))
            final = (
                "graduado"
                if aleatorio.random() < 0.7
                else aleatorio.choice(("retirado_formal", "cancelado"))
            )
            meses = 60 if final == "graduado" else aleatorio.randint(6, 40)
            fecha_final = min(
                inicio + dt.timedelta(days=30 * meses),
                PERIODOS[0][1] - dt.timedelta(days=30),
            )
            estados_filas.append((estudiante.codigo, final, fecha_final))

        matriculas_plan: list[tuple[_Estudiante, PeriodoAcademico, int]] = []
        for indice, periodo in enumerate(objetos_periodo):
            ordinal = _ordinal(periodo.identificador)
            if indice > 0:
                for _ in range(volumen.nuevos_por_periodo):
                    estudiante = _Estudiante(
                        codigo_para(periodo.identificador),
                        nombre_aleatorio(),
                        periodo.identificador,
                        1,
                    )
                    poblacion.append(estudiante)
                    estados_filas.append(
                        (
                            estudiante.codigo,
                            "activo",
                            periodo.fecha_inicio - dt.timedelta(days=7),
                        )
                    )
            for estudiante in poblacion:
                if estudiante.aplazado_hasta == ordinal:
                    estudiante.activo, estudiante.aplazado_hasta = True, None
                    estados_filas.append(
                        (
                            estudiante.codigo,
                            "activo",
                            periodo.fecha_inicio - dt.timedelta(days=7),
                        )
                    )
                if estudiante.activo and estudiante.aplazado_hasta is None:
                    matriculas_plan.append((estudiante, periodo, estudiante.semestre))
            # Transición al período siguiente (solo si ese período ya inició).
            siguiente = (
                objetos_periodo[indice + 1]
                if indice + 1 < len(objetos_periodo)
                else None
            )
            if siguiente is None:
                continue
            for estudiante, plan_periodo, _semestre in [
                m for m in matriculas_plan if m[1] is periodo
            ]:
                azar = aleatorio.random()
                if estudiante.semestre == 10:
                    if azar < 0.85:
                        estudiante.activo = False
                        estados_filas.append(
                            (
                                estudiante.codigo,
                                "graduado",
                                periodo.fecha_fin + dt.timedelta(days=12),
                            )
                        )
                    continue
                if azar < 0.03:
                    estudiante.aplazado_hasta = ordinal + 2
                    estados_filas.append(
                        (
                            estudiante.codigo,
                            "aplazo_semestre",
                            siguiente.fecha_inicio - dt.timedelta(days=14),
                        )
                    )
                elif azar < 0.12:
                    estudiante.activo = False
                    if azar < 0.065:
                        estados_filas.append(
                            (
                                estudiante.codigo,
                                aleatorio.choice(("retirado_formal", "cancelado")),
                                periodo.fecha_fin + dt.timedelta(days=20),
                            )
                        )
                estudiante.semestre += 1

        # Inserción de estudiantes e historial.
        todos = poblacion + historicos
        _insertar(
            Estudiante,
            [
                {
                    "codigo": e.codigo,
                    "nombres": e.nombres,
                    "correo": f"{e.codigo}@{DOMINIO_ESTUDIANTES}",
                    "programa_academico_id": programa_id,
                    "periodo_ingreso": e.cohorte,
                }
                for e in todos
            ],
        )
        ids_estudiante = dict(
            db.session.execute(select(Estudiante.codigo, Estudiante.id)).all()
        )
        for estudiante in todos:
            estudiante.id = ids_estudiante[estudiante.codigo]
        _insertar(
            HistorialEstadoEstudiante,
            [
                {
                    "estudiante_id": ids_estudiante[codigo],
                    "estado_estudiante_id": estados[estado],
                    "fecha_efectiva": fecha,
                    "registrado_por_usuario_id": administrador.id,
                }
                for codigo, estado, fecha in estados_filas
            ],
        )
        resumen["Estudiantes"] = len(todos)
        resumen["Registros de estado"] = len(estados_filas)

        _insertar(
            MatriculaPeriodo,
            [
                {
                    "estudiante_id": e.id,
                    "periodo_academico_id": p.id,
                    "semestre_cursado": s,
                }
                for e, p, s in matriculas_plan
            ],
        )
        ids_matricula = {
            (est, per): mid
            for mid, est, per in db.session.execute(
                select(
                    MatriculaPeriodo.id,
                    MatriculaPeriodo.estudiante_id,
                    MatriculaPeriodo.periodo_academico_id,
                )
            )
        }
        resumen["Matrículas"] = len(matriculas_plan)

        # --- Inscripciones ------------------------------------------------------
        avisar("Generando inscripciones, asistencia y notas...")
        cursos_por_asignatura: dict[tuple[int, int], list[Curso]] = {}
        for periodo_id, lista_cursos in cursos_periodo.items():
            for curso, asignatura in lista_cursos:
                cursos_por_asignatura.setdefault(
                    (periodo_id, asignatura.id), []
                ).append(curso)
        inscripciones_filas: list[dict] = []
        perfil: dict[tuple[int, int], tuple[float, float, Optional[dt.date]]] = {}
        for estudiante, periodo, semestre in matriculas_plan:
            elegidas = list(por_nivel.get(semestre, []))
            vecino = semestre - 1 if semestre > 1 else 2
            if aleatorio.random() < 0.9 and por_nivel.get(vecino):
                elegidas.append(aleatorio.choice(por_nivel[vecino]))
            matricula_id = ids_matricula[(estudiante.id, periodo.id)]
            for asignatura in elegidas:
                curso = aleatorio.choice(
                    cursos_por_asignatura[(periodo.id, asignatura.id)]
                )
                retiro = None
                if aleatorio.random() < 0.02:
                    retiro = periodo.fecha_inicio + dt.timedelta(
                        days=aleatorio.randint(20, 90)
                    )
                    if retiro >= hoy:
                        retiro = None
                inscripciones_filas.append(
                    {
                        "matricula_periodo_id": matricula_id,
                        "curso_id": curso.id,
                        "periodo_academico_id": periodo.id,
                        "retirada_en": retiro,
                    }
                )
                ausentismo = aleatorio.choices(
                    (
                        aleatorio.uniform(0, 0.06),
                        aleatorio.uniform(0.08, 0.18),
                        aleatorio.uniform(0.2, 0.4),
                    ),
                    weights=(70, 20, 10),
                )[0]
                media = min(4.9, max(1.6, aleatorio.gauss(3.6, 0.6) - ausentismo * 2))
                perfil[(matricula_id, curso.id)] = (ausentismo, media, retiro)
        _insertar(Inscripcion, inscripciones_filas)
        resumen["Inscripciones"] = len(inscripciones_filas)
        inscritos_por_curso: dict[
            int, list[tuple[int, float, float, Optional[dt.date]]]
        ] = {}
        for iid, mid, cid in db.session.execute(
            select(
                Inscripcion.id, Inscripcion.matricula_periodo_id, Inscripcion.curso_id
            )
        ):
            ausentismo, media, retiro = perfil[(mid, cid)]
            inscritos_por_curso.setdefault(cid, []).append(
                (iid, ausentismo, media, retiro)
            )

        # --- Asistencia y notas según el estado de cada corte ---------------------
        sesiones_por_curso: dict[int, list[tuple[int, dt.date, dt.time]]] = {}
        for sid, cid, fecha, fin in db.session.execute(
            select(
                SesionClase.id,
                SesionClase.curso_id,
                SesionClase.fecha,
                SesionClase.hora_fin,
            )
        ):
            sesiones_por_curso.setdefault(cid, []).append((sid, fecha, fin))
        ausencias_filas: list[dict] = []
        notas_filas: list[dict] = []
        registros_filas: list[dict] = []
        registradas: list[tuple[int, int, dt.datetime]] = []
        limite_asistencia = hoy - dt.timedelta(days=2)
        for periodo in objetos_periodo:
            cortes = cortes_por_periodo[periodo.id]
            for curso, _asignatura in cursos_periodo[periodo.id]:
                profesor_id = curso.profesor_usuario_id
                inscritos = inscritos_por_curso.get(curso.id, [])
                demo = profesor_id in profesores[:2]
                # En los cursos de profe1 y profe2 quedan sesiones recientes sin
                # registrar para demostrar RF-28.
                limite = limite_asistencia - dt.timedelta(days=7 if demo else 0)
                for sid, fecha, fin in sesiones_por_curso.get(curso.id, []):
                    if fecha > limite:
                        continue
                    registradas.append(
                        (sid, profesor_id, dt.datetime.combine(fecha, fin))
                    )
                    for iid, ausentismo, _media, retiro in inscritos:
                        if (
                            retiro is None or retiro > fecha
                        ) and aleatorio.random() < ausentismo:
                            ausencias_filas.append(
                                {
                                    "sesion_clase_id": sid,
                                    "inscripcion_id": iid,
                                    "ausente": True,
                                    "registrada_por_usuario_id": profesor_id,
                                }
                            )
                for corte in cortes:
                    if hoy < corte.fecha_inicio:
                        continue
                    cerrado = corte.cerrado_en is not None
                    vencida_carga = hoy > corte.fecha_fin
                    if cerrado or (
                        vencida_carga and not demo and aleatorio.random() < 0.8
                    ):
                        cobertura, enviado = 1.0, True
                    elif demo:
                        cobertura, enviado = 0.0, False
                    else:
                        cobertura, enviado = aleatorio.choice((0.0, 0.6, 0.9)), False
                    for iid, _ausentismo, media, retiro in inscritos:
                        if retiro is not None and retiro <= corte.fecha_fin:
                            continue
                        if enviado or aleatorio.random() < cobertura:
                            notas_filas.append(
                                {
                                    "inscripcion_id": iid,
                                    "corte_id": corte.id,
                                    "nota": _nota(aleatorio, media),
                                    "registrada_por_usuario_id": profesor_id,
                                }
                            )
                    if enviado:
                        registros_filas.append(
                            {
                                "curso_id": curso.id,
                                "corte_id": corte.id,
                                "estado": "cerrado" if cerrado else "enviado",
                                "enviado_en": dt.datetime.combine(
                                    corte.limite_carga, dt.time(17, 0)
                                ),
                                "enviado_por_usuario_id": profesor_id,
                            }
                        )
                    elif cobertura:
                        registros_filas.append(
                            {
                                "curso_id": curso.id,
                                "corte_id": corte.id,
                                "estado": "pendiente",
                            }
                        )
        _insertar(Ausencia, ausencias_filas)
        _insertar(NotaCorte, notas_filas)
        _insertar(RegistroCursoCorte, registros_filas)
        for inicio in range(0, len(registradas), 2000):
            lote = registradas[inicio : inicio + 2000]
            db.session.execute(
                SesionClase.__table__.update()
                .where(SesionClase.__table__.c.id == bindparam("sid"))
                .values(
                    asistencia_registrada_en=bindparam("cuando"),
                    asistencia_registrada_por_usuario_id=bindparam("quien"),
                ),
                [{"sid": s, "quien": q, "cuando": c} for s, q, c in lote],
            )
        resumen["Sesiones con asistencia registrada"] = len(registradas)
        resumen["Ausencias"] = len(ausencias_filas)
        resumen["Notas de corte"] = len(notas_filas)

        bitacora.registrar_evento(
            bitacora.EVENTO_CAMBIO_ADMINISTRATIVO,
            usuario_id=administrador.id,
            entidad="periodos_academicos",
            detalle=(
                f"Generación de datos de prueba (RF-25), semilla {semilla}: "
                f"{len(todos)} estudiantes, {resumen['Cursos']} cursos"
            ),
        )
        db.session.commit()
        return resumen
    except Exception:
        db.session.rollback()
        raise
