"""Carga de estudiantes e inscripciones desde un archivo CSV (RF-24).

Flujo en dos pasos: ``analizar`` valida el archivo completo sin escribir nada y
devuelve el resumen (nuevos, actualizados y filas con error con su número y
motivo); ``aplicar`` vuelve a validar el mismo archivo y guarda, en una sola
transacción, las filas válidas. La carga queda en la bitácora.

Columnas (separador punto y coma o coma, UTF-8 o Windows-1252):
``codigo;nombres;correo;periodo_ingreso;periodo;asignatura;curso;semestre_cursado``.
Las cuatro últimas son opcionales como grupo: vacías = solo el estudiante.

Todas las consultas se hacen por lotes (una por tipo de dato), así que el
tiempo no crece con una consulta por fila.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from flask import current_app
from sqlalchemy import select

from plasea.modelos import (
    Asignatura,
    Curso,
    EstadoEstudiante,
    Estudiante,
    HistorialEstadoEstudiante,
    Inscripcion,
    MatriculaPeriodo,
    PeriodoAcademico,
    ProgramaAcademico,
    db,
)
from plasea.servicios import bitacora, estudiantes
from plasea.servicios.comunes import ErrorNegocio

EVENTO_IMPORTACION = "importacion"
TAMANO_MAXIMO_BYTES = 5 * 1024 * 1024
COLUMNAS_ESTUDIANTE = ("codigo", "nombres", "correo", "periodo_ingreso")
COLUMNAS_INSCRIPCION = ("periodo", "asignatura", "curso", "semestre_cursado")
COLUMNAS = COLUMNAS_ESTUDIANTE + COLUMNAS_INSCRIPCION
_INICIOS_FORMULA = ("=", "+", "-", "@", "\t", "\r")
_PATRON_TOKEN = re.compile(r"^[0-9a-f]{32}$")
_VIGENCIA_TEMPORAL_SEGUNDOS = 3600

ACCION_NUEVO = "nuevo"
ACCION_ACTUALIZADO = "actualizado"
ACCION_SIN_CAMBIOS = "sin_cambios"
ACCION_REPETIDO = "repetido"


@dataclass
class FilaAnalizada:
    """Resultado de validar una fila del archivo."""

    numero: int
    codigo: str
    nombres: str
    accion_estudiante: Optional[str] = None
    inscripcion: Optional[str] = None
    errores: list[str] = field(default_factory=list)

    @property
    def valida(self) -> bool:
        """La fila no tiene errores."""
        return not self.errores


@dataclass
class ResumenImportacion:
    """Resumen previo (o final) de la carga (RF-24)."""

    filas: list[FilaAnalizada]
    nuevos: int = 0
    actualizados: int = 0
    sin_cambios: int = 0
    inscripciones: int = 0

    @property
    def con_error(self) -> list[FilaAnalizada]:
        """Filas con error, con su número y motivo."""
        return [fila for fila in self.filas if not fila.valida]

    @property
    def validas(self) -> int:
        """Número de filas que se guardarían."""
        return sum(1 for fila in self.filas if fila.valida)


@dataclass
class _Datos:
    """Datos normalizados de una fila válida."""

    codigo: str
    nombres: str
    correo: str
    cohorte: str
    curso: Optional[Curso] = None
    semestre: Optional[int] = None


# ---------------------------------------------------------------------------
# Lectura del archivo
# ---------------------------------------------------------------------------


def decodificar(contenido: bytes) -> str:
    """Decodifica el archivo: UTF-8 (con o sin BOM) o Windows-1252 (Excel).

    Raises:
        ErrorNegocio: archivo vacío o demasiado grande.
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-24
    if not contenido or not contenido.strip():
        raise ErrorNegocio("El archivo está vacío.")
    if len(contenido) > TAMANO_MAXIMO_BYTES:
        raise ErrorNegocio("El archivo supera el tamaño máximo de 5 MB.")
    try:
        return contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        return contenido.decode("cp1252", errors="replace")


def leer_filas(texto: str) -> list[tuple[int, dict[str, str]]]:
    """Lee las filas del CSV como diccionarios por nombre de columna.

    Returns:
        Pares (número de fila en el archivo, valores). La fila 1 es el encabezado.

    Raises:
        ErrorNegocio: encabezado incompleto o sin filas de datos.
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-24
    primera_linea = texto.splitlines()[0] if texto else ""
    separador = ";" if primera_linea.count(";") >= primera_linea.count(",") else ","
    lector = csv.reader(io.StringIO(texto), delimiter=separador)
    try:
        encabezado = [columna.strip().lower() for columna in next(lector)]
    except StopIteration as error:
        raise ErrorNegocio("El archivo está vacío.") from error
    faltantes = [columna for columna in COLUMNAS if columna not in encabezado]
    if faltantes:
        raise ErrorNegocio(
            "Faltan columnas en el encabezado: "
            + ", ".join(faltantes)
            + ". Descargue la plantilla y use sus nombres de columna."
        )
    posiciones = {columna: encabezado.index(columna) for columna in COLUMNAS}
    filas: list[tuple[int, dict[str, str]]] = []
    for numero, valores in enumerate(lector, start=2):
        if not any(valor.strip() for valor in valores):
            continue
        filas.append(
            (
                numero,
                {
                    columna: (valores[i].strip() if i < len(valores) else "")
                    for columna, i in posiciones.items()
                },
            )
        )
    if not filas:
        raise ErrorNegocio("El archivo no tiene filas de datos.")
    return filas


def generar_plantilla() -> bytes:
    """Plantilla descargable con el encabezado y dos filas de ejemplo ficticias."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-24
    salida = io.StringIO()
    escritor = csv.writer(salida, delimiter=";", lineterminator="\r\n")
    escritor.writerow(COLUMNAS)
    escritor.writerow(
        [
            "20261001",
            "Nombre Apellido Ejemplo",
            "20261001@estudiantes.plasea.edu.co",
            "2026-1",
            "2026-2",
            "ISI501",
            "T01",
            "2",
        ]
    )
    escritor.writerow(
        [
            "20261002",
            "Otro Estudiante Ejemplo",
            "20261002@estudiantes.plasea.edu.co",
            "2026-2",
            "",
            "",
            "",
            "",
        ]
    )
    return ("﻿" + salida.getvalue()).encode("utf-8")


# ---------------------------------------------------------------------------
# Archivo temporal entre la validación y la confirmación
# ---------------------------------------------------------------------------


def _carpeta_temporal() -> Path:
    """Carpeta privada de la instancia para las cargas pendientes de confirmar."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-24
    carpeta = Path(current_app.instance_path) / "importaciones"
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta


def guardar_temporal(contenido: bytes) -> str:
    """Guarda el archivo validado hasta su confirmación y devuelve un token."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-24
    carpeta = _carpeta_temporal()
    limite = time.time() - _VIGENCIA_TEMPORAL_SEGUNDOS
    for antiguo in carpeta.glob("*.csv"):
        if antiguo.stat().st_mtime < limite:
            antiguo.unlink(missing_ok=True)
    token = secrets.token_hex(16)
    (carpeta / f"{token}.csv").write_bytes(contenido)
    return token


def _ruta_temporal(token: Optional[str]) -> Path:
    """Ruta del archivo temporal; el token se valida antes de usarlo."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-24
    if not token or not _PATRON_TOKEN.match(token):
        raise ErrorNegocio("No hay una carga pendiente de confirmar.")
    return _carpeta_temporal() / f"{token}.csv"


def leer_temporal(token: Optional[str]) -> bytes:
    """Contenido de una carga pendiente.

    Raises:
        ErrorNegocio: la carga no existe o venció.
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-24
    ruta = _ruta_temporal(token)
    if not ruta.is_file():
        raise ErrorNegocio("La carga pendiente venció. Vuelva a validar el archivo.")
    return ruta.read_bytes()


def eliminar_temporal(token: Optional[str]) -> None:
    """Elimina el archivo temporal de una carga (confirmada o cancelada)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-24
    try:
        _ruta_temporal(token).unlink(missing_ok=True)
    except ErrorNegocio:
        return


# ---------------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------------


def _estado_en(
    historial: list[HistorialEstadoEstudiante], fecha: dt.date
) -> Optional[str]:
    """Código del estado vigente en una fecha según un historial ordenado."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-24
    vigente = None
    for registro in historial:
        if registro.fecha_efectiva <= fecha:
            vigente = registro.estado_estudiante.codigo
    return vigente


def _validar_estado(
    historial: list[HistorialEstadoEstudiante], periodo: PeriodoAcademico
) -> Optional[str]:
    """Mismas reglas de RF-22 y RF-23 que la inscripción individual."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-24
    al_inicio = _estado_en(historial, periodo.fecha_inicio)
    if al_inicio in estudiantes.ESTADOS_TERMINALES:
        return (
            f"el estudiante no se puede inscribir en {periodo.identificador} por su "
            "estado"
        )
    referencia = min(estudiantes.hoy(), periodo.fecha_fin)
    if _estado_en(historial, referencia) != estudiantes.ESTADO_ACTIVO:
        return "solo se inscriben estudiantes activos"
    return None


def _analizar(contenido: bytes) -> tuple[ResumenImportacion, dict[int, _Datos]]:
    """Valida todo el archivo contra la base de datos sin escribir nada."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-24
    filas = leer_filas(decodificar(contenido))

    # --- Lotes de consulta -------------------------------------------------
    codigos = {valores["codigo"].strip() for _, valores in filas}
    existentes = {
        e.codigo: e
        for e in db.session.scalars(
            select(Estudiante).where(Estudiante.codigo.in_(codigos))
        )
    }
    historiales: dict[int, list[HistorialEstadoEstudiante]] = {}
    if existentes:
        for registro in db.session.scalars(
            select(HistorialEstadoEstudiante)
            .join(HistorialEstadoEstudiante.estado_estudiante)
            .where(
                HistorialEstadoEstudiante.estudiante_id.in_(
                    [e.id for e in existentes.values()]
                )
            )
            .order_by(
                HistorialEstadoEstudiante.fecha_efectiva,
                HistorialEstadoEstudiante.id,
            )
        ):
            historiales.setdefault(registro.estudiante_id, []).append(registro)
    identificadores = {valores["periodo"] for _, valores in filas if valores["periodo"]}
    periodos = {
        p.identificador: p
        for p in db.session.scalars(
            select(PeriodoAcademico).where(
                PeriodoAcademico.identificador.in_(identificadores)
            )
        )
    }
    cursos: dict[tuple[str, str, str], Curso] = {}
    if periodos:
        for curso, codigo_asignatura, identificador in db.session.execute(
            select(Curso, Asignatura.codigo, PeriodoAcademico.identificador)
            .join(Asignatura, Asignatura.id == Curso.asignatura_id)
            .join(PeriodoAcademico, PeriodoAcademico.id == Curso.periodo_academico_id)
            .where(Curso.periodo_academico_id.in_([p.id for p in periodos.values()]))
        ):
            cursos[(identificador, codigo_asignatura, curso.codigo)] = curso
    matriculas: dict[tuple[int, int], MatriculaPeriodo] = {}
    inscritos: dict[tuple[int, int], Inscripcion] = {}
    if existentes and periodos:
        for matricula in db.session.scalars(
            select(MatriculaPeriodo).where(
                MatriculaPeriodo.estudiante_id.in_([e.id for e in existentes.values()]),
                MatriculaPeriodo.periodo_academico_id.in_(
                    [p.id for p in periodos.values()]
                ),
            )
        ):
            matriculas[(matricula.estudiante_id, matricula.periodo_academico_id)] = (
                matricula
            )
        if matriculas:
            for inscripcion in db.session.scalars(
                select(Inscripcion).where(
                    Inscripcion.matricula_periodo_id.in_(
                        [m.id for m in matriculas.values()]
                    )
                )
            ):
                inscritos[(inscripcion.matricula_periodo_id, inscripcion.curso_id)] = (
                    inscripcion
                )

    # --- Validación fila por fila -----------------------------------------
    resumen = ResumenImportacion(filas=[])
    datos_validos: dict[int, _Datos] = {}
    primeros: dict[str, tuple[str, str, str]] = {}
    semestres_archivo: dict[tuple[str, int], int] = {}
    cursos_archivo: set[tuple[str, int]] = set()
    for numero, valores in filas:
        fila = FilaAnalizada(numero, valores["codigo"], valores["nombres"])
        resumen.filas.append(fila)
        if any(v.startswith(_INICIOS_FORMULA) for v in valores.values() if v):
            fila.errores.append(
                "Hay un valor que empieza con =, +, - o @; no se aceptan fórmulas."
            )
            continue
        try:
            codigo, nombres, correo, cohorte = estudiantes.normalizar_formato(
                valores["codigo"],
                valores["nombres"],
                valores["correo"],
                valores["periodo_ingreso"],
            )
        except ErrorNegocio as fallo:
            fila.errores.append(fallo.mensaje)
            continue
        fila.codigo, fila.nombres = codigo, nombres
        datos = _Datos(codigo, nombres, correo, cohorte)

        if codigo in primeros:
            if primeros[codigo] != (nombres, correo, cohorte):
                fila.errores.append(
                    "El código aparece antes en el archivo con otros nombres, correo "
                    "o cohorte."
                )
                continue
            fila.accion_estudiante = ACCION_REPETIDO
        else:
            existente = existentes.get(codigo)
            if existente is None:
                fila.accion_estudiante = ACCION_NUEVO
            elif (existente.nombres, existente.correo, existente.periodo_ingreso) != (
                nombres,
                correo,
                cohorte,
            ):
                fila.accion_estudiante = ACCION_ACTUALIZADO
            else:
                fila.accion_estudiante = ACCION_SIN_CAMBIOS

        grupo = [valores[c] for c in COLUMNAS_INSCRIPCION]
        if any(grupo):
            if not all(grupo):
                fila.errores.append(
                    "Para inscribir, complete período, asignatura, curso y semestre."
                )
                continue
            periodo = periodos.get(valores["periodo"])
            if periodo is None:
                fila.errores.append(f"No existe el período {valores['periodo']}.")
                continue
            curso = cursos.get(
                (
                    periodo.identificador,
                    valores["asignatura"].upper(),
                    valores["curso"].upper(),
                )
            )
            if curso is None:
                fila.errores.append(
                    f"No existe el curso {valores['asignatura'].upper()} "
                    f"{valores['curso'].upper()} en {periodo.identificador}."
                )
                continue
            if (
                not valores["semestre_cursado"].isdigit()
                or not 1 <= int(valores["semestre_cursado"]) <= 10
            ):
                fila.errores.append("El semestre cursado debe estar entre 1 y 10.")
                continue
            semestre = int(valores["semestre_cursado"])
            clave_archivo = (codigo, periodo.id)
            if semestres_archivo.get(clave_archivo, semestre) != semestre:
                fila.errores.append(
                    "El archivo trae otro semestre para el mismo estudiante y período."
                )
                continue
            if (codigo, curso.id) in cursos_archivo:
                fila.errores.append(
                    "La inscripción en este curso está repetida en el archivo."
                )
                continue
            existente = existentes.get(codigo)
            if existente is not None:
                motivo = _validar_estado(historiales.get(existente.id, []), periodo)
                if motivo:
                    fila.errores.append(motivo[0].upper() + motivo[1:] + ".")
                    continue
                matricula = matriculas.get((existente.id, periodo.id))
                if matricula is not None and matricula.semestre_cursado != semestre:
                    fila.errores.append(
                        f"Ya está matriculado en {periodo.identificador} cursando el "
                        f"semestre {matricula.semestre_cursado}."
                    )
                    continue
                if matricula is not None and (matricula.id, curso.id) in inscritos:
                    fila.errores.append("Ya está inscrito (o se retiró) en este curso.")
                    continue
            semestres_archivo[clave_archivo] = semestre
            cursos_archivo.add((codigo, curso.id))
            datos.curso, datos.semestre = curso, semestre
            fila.inscripcion = (
                f"{valores['asignatura'].upper()} {curso.codigo} · "
                f"{periodo.identificador}"
            )

        primeros.setdefault(codigo, (nombres, correo, cohorte))
        datos_validos[numero] = datos

    for fila in resumen.filas:
        if not fila.valida:
            continue
        if fila.accion_estudiante == ACCION_NUEVO:
            resumen.nuevos += 1
        elif fila.accion_estudiante == ACCION_ACTUALIZADO:
            resumen.actualizados += 1
        elif fila.accion_estudiante == ACCION_SIN_CAMBIOS:
            resumen.sin_cambios += 1
        if fila.inscripcion:
            resumen.inscripciones += 1
    return resumen, datos_validos


def analizar(contenido: bytes) -> ResumenImportacion:
    """Valida el archivo y devuelve el resumen previo; no guarda nada (RF-24)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-24
    resumen, _ = _analizar(contenido)
    return resumen


def aplicar(contenido: bytes, actor_id: int) -> ResumenImportacion:
    """Vuelve a validar el archivo y guarda las filas válidas (RF-24).

    Las filas con error se omiten (el resumen las informa). Los estudiantes
    nuevos quedan activos desde la fecha más temprana entre hoy y el inicio del
    período en que se inscriben, para que la inscripción cumpla RF-23.

    Raises:
        ErrorNegocio: archivo ilegible o sin filas válidas.
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-24
    try:
        resumen, datos_validos = _analizar(contenido)
        if not datos_validos:
            raise ErrorNegocio("No hay filas válidas para guardar.")
        programa_id = db.session.scalar(
            select(ProgramaAcademico.id).order_by(ProgramaAcademico.id).limit(1)
        )
        activo_id = db.session.scalar(
            select(EstadoEstudiante.id).where(
                EstadoEstudiante.codigo == estudiantes.ESTADO_ACTIVO
            )
        )
        hoy = estudiantes.hoy()
        codigos = {d.codigo for d in datos_validos.values()}
        por_codigo = {
            e.codigo: e
            for e in db.session.scalars(
                select(Estudiante).where(Estudiante.codigo.in_(codigos))
            )
        }
        fecha_activo: dict[str, dt.date] = {}
        for datos in datos_validos.values():
            inicio = datos.curso.periodo_academico.fecha_inicio if datos.curso else hoy
            fecha_activo[datos.codigo] = min(
                fecha_activo.get(datos.codigo, hoy), inicio, hoy
            )

        nuevos: list[Estudiante] = []
        for datos in datos_validos.values():
            estudiante = por_codigo.get(datos.codigo)
            if estudiante is None:
                estudiante = Estudiante(
                    codigo=datos.codigo,
                    nombres=datos.nombres,
                    correo=datos.correo,
                    periodo_ingreso=datos.cohorte,
                    programa_academico_id=programa_id,
                )
                db.session.add(estudiante)
                por_codigo[datos.codigo] = estudiante
                nuevos.append(estudiante)
            else:
                estudiante.nombres = datos.nombres
                estudiante.correo = datos.correo
                estudiante.periodo_ingreso = datos.cohorte
        db.session.flush()
        db.session.add_all(
            HistorialEstadoEstudiante(
                estudiante_id=estudiante.id,
                estado_estudiante_id=activo_id,
                fecha_efectiva=fecha_activo[estudiante.codigo],
                registrado_por_usuario_id=actor_id,
            )
            for estudiante in nuevos
        )

        matriculas: dict[tuple[int, int], MatriculaPeriodo] = {
            (m.estudiante_id, m.periodo_academico_id): m
            for m in db.session.scalars(
                select(MatriculaPeriodo).where(
                    MatriculaPeriodo.estudiante_id.in_(
                        [e.id for e in por_codigo.values()]
                    )
                )
            )
        }
        inscripciones_nuevas = 0
        for datos in datos_validos.values():
            if datos.curso is None:
                continue
            estudiante = por_codigo[datos.codigo]
            clave = (estudiante.id, datos.curso.periodo_academico_id)
            matricula = matriculas.get(clave)
            if matricula is None:
                matricula = MatriculaPeriodo(
                    estudiante_id=estudiante.id,
                    periodo_academico_id=datos.curso.periodo_academico_id,
                    semestre_cursado=datos.semestre,
                )
                db.session.add(matricula)
                db.session.flush()
                matriculas[clave] = matricula
            db.session.add(
                Inscripcion(
                    matricula_periodo_id=matricula.id,
                    curso_id=datos.curso.id,
                    periodo_academico_id=datos.curso.periodo_academico_id,
                )
            )
            inscripciones_nuevas += 1
        bitacora.registrar_evento(
            EVENTO_IMPORTACION,
            usuario_id=actor_id,
            entidad="estudiantes",
            detalle=(
                f"Carga CSV: {resumen.nuevos} nuevos, {resumen.actualizados} "
                f"actualizados, {inscripciones_nuevas} inscripciones, "
                f"{len(resumen.con_error)} filas con error omitidas"
            ),
        )
        db.session.commit()
        return resumen
    except Exception:
        db.session.rollback()
        raise
