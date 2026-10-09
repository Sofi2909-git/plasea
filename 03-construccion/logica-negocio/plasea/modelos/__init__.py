"""Modelos SQLAlchemy de PLASEA.

Mapean una a una las 29 tablas de ``02-arquitectura/modelo-datos/plasea_esquema.sql``
(fuente de verdad, documentada en ``diccionario-datos.md``). No agregan ni quitan
columnas. Los nombres de restricciones e indices son los del script SQL.

Notas de mapeo:
- Los tipos sin signo de MariaDB se declaran como variantes del dialecto; en otro
  motor se usan los tipos genericos (RNF-08).
- ``sesiones_clase.duracion_horas`` y ``reaperturas_curso.vigente_marca`` son
  columnas calculadas por la base de datos: la aplicacion nunca las escribe.
- ``actualizado_en`` tiene ``ON UPDATE CURRENT_TIMESTAMP`` en la base de datos;
  el ORM tambien la actualiza para no depender del motor.
- La vista ``vw_estudiantes_riesgo_alto`` no es una tabla y no se mapea aqui.
- Las fechas y horas se guardan en hora de Colombia (la conexion fija
  ``time_zone = '-05:00'``).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Optional

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

db = SQLAlchemy()

# ---------------------------------------------------------------------------
# Tipos equivalentes a los del esquema SQL
# ---------------------------------------------------------------------------
_DIALECTOS = ("mysql", "mariadb")

ID_TIPO = BigInteger().with_variant(mysql.BIGINT(unsigned=True), *_DIALECTOS)
TINYINT_SIN_SIGNO = SmallInteger().with_variant(
    mysql.TINYINT(unsigned=True), *_DIALECTOS
)
TINYINT_CON_SIGNO = SmallInteger().with_variant(mysql.TINYINT(), *_DIALECTOS)
SMALLINT_SIN_SIGNO = Integer().with_variant(mysql.SMALLINT(unsigned=True), *_DIALECTOS)
HASH_SHA256 = CHAR(64).with_variant(
    mysql.CHAR(64, charset="ascii", collation="ascii_bin"), *_DIALECTOS
)
HASH_CONTRASENA = String(255).with_variant(
    mysql.VARCHAR(255, charset="ascii", collation="ascii_bin"), *_DIALECTOS
)
DATETIME_MILISEGUNDOS = DateTime().with_variant(mysql.DATETIME(fsp=3), *_DIALECTOS)

_AHORA = text("CURRENT_TIMESTAMP")
_RESTRICT = {"ondelete": "RESTRICT", "onupdate": "RESTRICT"}


def _opciones_tabla(comentario: str) -> dict[str, Any]:
    """Devuelve las opciones comunes de tabla (motor, codificacion y comentario)."""
    return {
        "mysql_engine": "InnoDB",
        "mysql_charset": "utf8mb4",
        "mysql_collate": "utf8mb4_spanish_ci",
        "comment": comentario,
    }


def _fk(destino: str, nombre: str) -> ForeignKey:
    """Crea una llave foranea con nombre y acciones RESTRICT, como en el esquema."""
    return ForeignKey(destino, name=nombre, **_RESTRICT)


def _creado_en() -> Mapped[dt.datetime]:
    """Columna ``creado_en`` con valor por defecto de la base de datos."""
    return mapped_column(DateTime, nullable=False, server_default=_AHORA)


def _actualizado_en() -> Mapped[dt.datetime]:
    """Columna ``actualizado_en``; se actualiza en cada modificacion."""
    return mapped_column(
        DateTime,
        nullable=False,
        server_default=_AHORA,
        onupdate=func.current_timestamp(),
    )


# ===========================================================================
# E1. ACCESO Y CUENTAS (RF-01 a RF-12)
# ===========================================================================


class Rol(db.Model):
    """Catalogo de los 3 roles fijos (RF-02)."""

    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("codigo", name="uq_roles_codigo"),
        UniqueConstraint("nombre", name="uq_roles_nombre"),
        _opciones_tabla("Catalogo de los 3 roles fijos (RF-02)"),
    )

    id: Mapped[int] = mapped_column(ID_TIPO, primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="Identificador estable usado por la aplicacion",
    )
    nombre: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="Nombre para mostrar"
    )

    usuarios: Mapped[list[Usuario]] = relationship(back_populates="rol")


class Usuario(db.Model):
    """Cuentas de usuario. Nunca se eliminan, solo se desactivan (RF-11)."""

    __tablename__ = "usuarios"
    __table_args__ = (
        UniqueConstraint("correo", name="uq_usuarios_correo"),
        Index("ix_usuarios_rol_estado", "rol_id", "estado_cuenta"),
        Index("ix_usuarios_nombre_completo", "nombre_completo"),
        CheckConstraint(
            "estado_cuenta IN ('pendiente_activacion','activa','inactiva','bloqueada')",
            name="ck_usuarios_estado_cuenta",
        ),
        CheckConstraint(
            "estado_cuenta NOT IN ('activa','bloqueada') "
            "OR contrasena_hash IS NOT NULL",
            name="ck_usuarios_hash_si_activa",
        ),
        _opciones_tabla(
            "Cuentas de usuario. Nunca se eliminan, solo se desactivan (RF-11)"
        ),
    )

    id: Mapped[int] = mapped_column(ID_TIPO, primary_key=True, autoincrement=True)
    nombre_completo: Mapped[str] = mapped_column(String(150), nullable=False)
    correo: Mapped[str] = mapped_column(
        String(254),
        nullable=False,
        comment="Correo institucional, unico sin distinguir mayusculas (RF-08)",
    )
    contrasena_hash: Mapped[Optional[str]] = mapped_column(
        HASH_CONTRASENA,
        nullable=True,
        comment=(
            "Solo el hash producido por la aplicacion; NULL mientras la cuenta "
            "esta pendiente de activacion"
        ),
    )
    rol_id: Mapped[int] = mapped_column(
        ID_TIPO, _fk("roles.id", "fk_usuarios_roles"), nullable=False
    )
    estado_cuenta: Mapped[str] = mapped_column(
        String(25),
        nullable=False,
        server_default=text("'pendiente_activacion'"),
        comment=(
            "pendiente_activacion | activa | inactiva | bloqueada "
            "(bloqueo administrativo, RF-11)"
        ),
    )
    intentos_fallidos: Mapped[int] = mapped_column(
        TINYINT_SIN_SIGNO,
        nullable=False,
        server_default=text("0"),
        comment="Intentos consecutivos fallidos (RF-05)",
    )
    bloqueo_hasta: Mapped[Optional[dt.datetime]] = mapped_column(
        DateTime,
        nullable=True,
        comment=(
            "Bloqueo temporal automatico por intentos fallidos (RF-05); "
            "NULL si no hay"
        ),
    )
    creado_en: Mapped[dt.datetime] = _creado_en()
    actualizado_en: Mapped[dt.datetime] = _actualizado_en()

    rol: Mapped[Rol] = relationship(back_populates="usuarios")


class TokenCuenta(db.Model):
    """Enlaces de un solo uso para activar cuenta y restablecer contrasena."""

    __tablename__ = "tokens_cuenta"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_tokens_cuenta_token_hash"),
        Index("ix_tokens_cuenta_usuario_proposito", "usuario_id", "proposito"),
        CheckConstraint(
            "proposito IN ('activacion','restablecimiento')",
            name="ck_tokens_cuenta_proposito",
        ),
        CheckConstraint(
            "token_hash REGEXP '^[0-9a-f]{64}$'", name="ck_tokens_cuenta_hash"
        ),
        CheckConstraint("vence_en > creado_en", name="ck_tokens_cuenta_vigencia"),
        _opciones_tabla(
            "Enlaces de un solo uso para activar cuenta y restablecer contrasena"
        ),
    )

    id: Mapped[int] = mapped_column(ID_TIPO, primary_key=True, autoincrement=True)
    usuario_id: Mapped[int] = mapped_column(
        ID_TIPO, _fk("usuarios.id", "fk_tokens_cuenta_usuarios"), nullable=False
    )
    proposito: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="activacion (RF-08/09) | restablecimiento (RF-06/07)",
    )
    token_hash: Mapped[str] = mapped_column(
        HASH_SHA256,
        nullable=False,
        comment=(
            "SHA-256 en hexadecimal del token enviado por correo; "
            "el token nunca se guarda"
        ),
    )
    creado_en: Mapped[dt.datetime] = _creado_en()
    vence_en: Mapped[dt.datetime] = mapped_column(
        DateTime,
        nullable=False,
        comment="Vigencia parametrizable en el archivo de configuracion",
    )
    usado_en: Mapped[Optional[dt.datetime]] = mapped_column(
        DateTime,
        nullable=True,
        comment="Uso unico: se llena al consumir el enlace",
    )
    invalidado_en: Mapped[Optional[dt.datetime]] = mapped_column(
        DateTime,
        nullable=True,
        comment="Se llena cuando un enlace nuevo o un cambio de estado lo reemplaza",
    )

    usuario: Mapped[Usuario] = relationship()


class SesionUsuario(db.Model):
    """Sesiones en el servidor (RF-03, RF-04, RF-07, RF-11)."""

    __tablename__ = "sesiones_usuario"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_sesiones_usuario_token_hash"),
        Index("ix_sesiones_usuario_usuario_cerrada", "usuario_id", "cerrada_en"),
        Index("ix_sesiones_usuario_rol", "rol_id"),
        CheckConstraint(
            "motivo_cierre IS NULL OR motivo_cierre IN ('cierre_voluntario',"
            "'inactividad','cuenta_desactivada','cuenta_bloqueada',"
            "'restablecimiento_contrasena')",
            name="ck_sesiones_usuario_motivo",
        ),
        CheckConstraint(
            "(cerrada_en IS NULL) = (motivo_cierre IS NULL)",
            name="ck_sesiones_usuario_cierre",
        ),
        _opciones_tabla(
            "Sesiones en el servidor: permiten cerrar, expirar e invalidar "
            "sesiones (RF-03, RF-04, RF-07, RF-11)"
        ),
    )

    id: Mapped[int] = mapped_column(ID_TIPO, primary_key=True, autoincrement=True)
    usuario_id: Mapped[int] = mapped_column(
        ID_TIPO, _fk("usuarios.id", "fk_sesiones_usuario_usuarios"), nullable=False
    )
    rol_id: Mapped[int] = mapped_column(
        ID_TIPO,
        _fk("roles.id", "fk_sesiones_usuario_roles"),
        nullable=False,
        comment=(
            "Rol vigente al iniciar sesion: un cambio de rol aplica desde el "
            "siguiente inicio (RF-10)"
        ),
    )
    token_hash: Mapped[str] = mapped_column(
        HASH_SHA256,
        nullable=False,
        comment="SHA-256 del identificador opaco guardado en la cookie de sesion",
    )
    creada_en: Mapped[dt.datetime] = mapped_column(
        DateTime, nullable=False, server_default=_AHORA
    )
    ultima_actividad_en: Mapped[dt.datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=_AHORA,
        comment="Base de la expiracion por inactividad (RF-04)",
    )
    cerrada_en: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)
    motivo_cierre: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)

    usuario: Mapped[Usuario] = relationship()
    rol: Mapped[Rol] = relationship()


# ===========================================================================
# E2. ESTRUCTURA ACADEMICA (RF-13 a RF-20)
# ===========================================================================


class ProgramaAcademico(db.Model):
    """Catalogo de programas (hoy solo Ingenieria de Sistemas)."""

    __tablename__ = "programas_academicos"
    __table_args__ = (
        UniqueConstraint("nombre", name="uq_programas_academicos_nombre"),
        _opciones_tabla(
            "Catalogo de programas (hoy solo Ingenieria de Sistemas; "
            "RF-13, RF-21, RF-53)"
        ),
    )

    id: Mapped[int] = mapped_column(ID_TIPO, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)


class Asignatura(db.Model):
    """Asignaturas (sinonimo de materias) - RF-13."""

    __tablename__ = "asignaturas"
    __table_args__ = (
        UniqueConstraint("codigo", name="uq_asignaturas_codigo"),
        Index("ix_asignaturas_programa", "programa_academico_id"),
        CheckConstraint("creditos IN (3,4)", name="ck_asignaturas_creditos"),
        CheckConstraint("horas_semanales > 0", name="ck_asignaturas_horas"),
        CheckConstraint("nivel BETWEEN 1 AND 10", name="ck_asignaturas_nivel"),
        _opciones_tabla("Asignaturas (sinonimo de materias) - RF-13"),
    )

    id: Mapped[int] = mapped_column(ID_TIPO, primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(String(20), nullable=False)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    programa_academico_id: Mapped[int] = mapped_column(
        ID_TIPO,
        _fk("programas_academicos.id", "fk_asignaturas_programas_academicos"),
        nullable=False,
    )
    creditos: Mapped[int] = mapped_column(
        TINYINT_SIN_SIGNO, nullable=False, comment="3 o 4"
    )
    horas_semanales: Mapped[int] = mapped_column(TINYINT_SIN_SIGNO, nullable=False)
    nivel: Mapped[int] = mapped_column(
        TINYINT_SIN_SIGNO, nullable=False, comment="Nivel de la carrera, 1 a 10"
    )
    creado_en: Mapped[dt.datetime] = _creado_en()
    actualizado_en: Mapped[dt.datetime] = _actualizado_en()

    programa_academico: Mapped[ProgramaAcademico] = relationship()
    cursos: Mapped[list[Curso]] = relationship(back_populates="asignatura")


class PeriodoAcademico(db.Model):
    """Semestres academicos (RF-16). El orden cronologico lo da fecha_inicio."""

    __tablename__ = "periodos_academicos"
    __table_args__ = (
        UniqueConstraint("identificador", name="uq_periodos_academicos_identificador"),
        UniqueConstraint("en_curso_marca", name="uq_periodos_academicos_en_curso"),
        Index("ix_periodos_academicos_fecha_inicio", "fecha_inicio"),
        CheckConstraint(
            "identificador REGEXP '^[0-9]{4}-[12]$'",
            name="ck_periodos_academicos_identificador",
        ),
        CheckConstraint(
            "fecha_fin > fecha_inicio", name="ck_periodos_academicos_fechas"
        ),
        CheckConstraint(
            "en_curso_marca IS NULL OR en_curso_marca = 1",
            name="ck_periodos_academicos_marca",
        ),
        _opciones_tabla(
            "Semestres academicos (RF-16). El orden cronologico lo da fecha_inicio"
        ),
    )

    id: Mapped[int] = mapped_column(ID_TIPO, primary_key=True, autoincrement=True)
    identificador: Mapped[str] = mapped_column(
        String(6), nullable=False, comment="Ejemplo: 2026-2"
    )
    fecha_inicio: Mapped[dt.date] = mapped_column(Date, nullable=False)
    fecha_fin: Mapped[dt.date] = mapped_column(
        Date,
        nullable=False,
        comment="Fin de las 16 semanas; la duracion exacta la valida la aplicacion",
    )
    en_curso_marca: Mapped[Optional[int]] = mapped_column(
        TINYINT_CON_SIGNO,
        nullable=True,
        server_default=text("NULL"),
        comment="1 = periodo en curso; NULL = no. UNIQUE garantiza uno solo (RF-16)",
    )
    creado_en: Mapped[dt.datetime] = _creado_en()
    actualizado_en: Mapped[dt.datetime] = _actualizado_en()

    cortes: Mapped[list[Corte]] = relationship(
        back_populates="periodo_academico", order_by="Corte.numero"
    )
    festivos: Mapped[list[Festivo]] = relationship(
        back_populates="periodo_academico", order_by="Festivo.fecha"
    )
    cursos: Mapped[list[Curso]] = relationship(back_populates="periodo_academico")


class Corte(db.Model):
    """Los 3 cortes de cada periodo con pesos, plazos y cierre (RF-17, RF-36, RF-37)."""

    __tablename__ = "cortes"
    __table_args__ = (
        UniqueConstraint(
            "periodo_academico_id", "numero", name="uq_cortes_periodo_numero"
        ),
        Index("ix_cortes_cerrado_por", "cerrado_por_usuario_id"),
        CheckConstraint("numero BETWEEN 1 AND 3", name="ck_cortes_numero"),
        CheckConstraint(
            "peso_porcentaje > 0 AND peso_porcentaje <= 100", name="ck_cortes_peso"
        ),
        CheckConstraint("fecha_inicio <= fecha_fin", name="ck_cortes_fechas"),
        CheckConstraint("limite_correccion > limite_carga", name="ck_cortes_limites"),
        CheckConstraint(
            "tipo_cierre IS NULL OR tipo_cierre IN ('manual','automatico')",
            name="ck_cortes_tipo_cierre",
        ),
        CheckConstraint(
            "(cerrado_en IS NULL) = (tipo_cierre IS NULL)",
            name="ck_cortes_cierre_completo",
        ),
        CheckConstraint(
            "tipo_cierre IS NULL OR ((tipo_cierre = 'manual') = "
            "(cerrado_por_usuario_id IS NOT NULL))",
            name="ck_cortes_cierre_responsable",
        ),
        _opciones_tabla(
            "Los 3 cortes de cada periodo con pesos, plazos y estado de cierre "
            "(RF-17, RF-36, RF-37)"
        ),
    )

    id: Mapped[int] = mapped_column(ID_TIPO, primary_key=True, autoincrement=True)
    periodo_academico_id: Mapped[int] = mapped_column(
        ID_TIPO,
        _fk("periodos_academicos.id", "fk_cortes_periodos_academicos"),
        nullable=False,
    )
    numero: Mapped[int] = mapped_column(
        TINYINT_SIN_SIGNO, nullable=False, comment="1, 2 o 3"
    )
    peso_porcentaje: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        comment=(
            "Por defecto 30, 30 y 40; la suma de 100 la valida la aplicacion (RF-17)"
        ),
    )
    fecha_inicio: Mapped[dt.date] = mapped_column(Date, nullable=False)
    fecha_fin: Mapped[dt.date] = mapped_column(Date, nullable=False)
    limite_carga: Mapped[dt.date] = mapped_column(Date, nullable=False)
    limite_correccion: Mapped[dt.date] = mapped_column(Date, nullable=False)
    cerrado_en: Mapped[Optional[dt.datetime]] = mapped_column(
        DateTime, nullable=True, comment="NULL = corte abierto"
    )
    tipo_cierre: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
        comment="manual (RF-36) | automatico (RF-37)",
    )
    cerrado_por_usuario_id: Mapped[Optional[int]] = mapped_column(
        ID_TIPO,
        _fk("usuarios.id", "fk_cortes_usuarios_cierre"),
        nullable=True,
        comment="Auditor que cerro; NULL si fue automatico",
    )
    aviso_resumen_enviado_en: Mapped[Optional[dt.datetime]] = mapped_column(
        DateTime,
        nullable=True,
        comment="Garantiza un solo correo de resumen por corte cerrado (RF-57)",
    )
    creado_en: Mapped[dt.datetime] = _creado_en()
    actualizado_en: Mapped[dt.datetime] = _actualizado_en()

    periodo_academico: Mapped[PeriodoAcademico] = relationship(back_populates="cortes")
    cerrado_por: Mapped[Optional[Usuario]] = relationship()


class Festivo(db.Model):
    """Festivos del periodo; no hay sesiones esos dias (RF-18, RF-19)."""

    __tablename__ = "festivos"
    __table_args__ = (
        UniqueConstraint(
            "periodo_academico_id", "fecha", name="uq_festivos_periodo_fecha"
        ),
        _opciones_tabla(
            "Festivos del periodo; no hay sesiones esos dias (RF-18, RF-19)"
        ),
    )

    id: Mapped[int] = mapped_column(ID_TIPO, primary_key=True, autoincrement=True)
    periodo_academico_id: Mapped[int] = mapped_column(
        ID_TIPO,
        _fk("periodos_academicos.id", "fk_festivos_periodos_academicos"),
        nullable=False,
    )
    fecha: Mapped[dt.date] = mapped_column(Date, nullable=False)

    periodo_academico: Mapped[PeriodoAcademico] = relationship(
        back_populates="festivos"
    )


class Curso(db.Model):
    """Cursos de una asignatura en un periodo, con su docente (RF-14)."""

    __tablename__ = "cursos"
    __table_args__ = (
        UniqueConstraint(
            "asignatura_id",
            "periodo_academico_id",
            "codigo",
            name="uq_cursos_asignatura_periodo_codigo",
        ),
        UniqueConstraint("id", "periodo_academico_id", name="uq_cursos_id_periodo"),
        Index(
            "ix_cursos_profesor_periodo",
            "profesor_usuario_id",
            "periodo_academico_id",
        ),
        Index("ix_cursos_periodo", "periodo_academico_id"),
        _opciones_tabla(
            "Cursos de una asignatura en un periodo, con su docente (RF-14)"
        ),
    )

    id: Mapped[int] = mapped_column(ID_TIPO, primary_key=True, autoincrement=True)
    asignatura_id: Mapped[int] = mapped_column(
        ID_TIPO, _fk("asignaturas.id", "fk_cursos_asignaturas"), nullable=False
    )
    periodo_academico_id: Mapped[int] = mapped_column(
        ID_TIPO,
        _fk("periodos_academicos.id", "fk_cursos_periodos_academicos"),
        nullable=False,
    )
    codigo: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="Ejemplo: T01, T02"
    )
    profesor_usuario_id: Mapped[int] = mapped_column(
        ID_TIPO,
        _fk("usuarios.id", "fk_cursos_usuarios_profesor"),
        nullable=False,
        comment=("Un solo docente por curso; la aplicacion exige rol Profesor (RF-14)"),
    )
    creado_en: Mapped[dt.datetime] = _creado_en()
    actualizado_en: Mapped[dt.datetime] = _actualizado_en()

    asignatura: Mapped[Asignatura] = relationship(back_populates="cursos")
    periodo_academico: Mapped[PeriodoAcademico] = relationship(back_populates="cursos")
    profesor: Mapped[Usuario] = relationship()
    bloques_horario: Mapped[list[BloqueHorario]] = relationship(
        back_populates="curso",
        order_by="(BloqueHorario.dia_semana, BloqueHorario.hora_inicio)",
    )
    sesiones_clase: Mapped[list[SesionClase]] = relationship(
        back_populates="curso",
        order_by="(SesionClase.fecha, SesionClase.hora_inicio)",
    )
    inscripciones: Mapped[list[Inscripcion]] = relationship(
        back_populates="curso",
        primaryjoin="Curso.id == Inscripcion.curso_id",
        foreign_keys="Inscripcion.curso_id",
    )


class BloqueHorario(db.Model):
    """Horario semanal del curso: sesiones de 1, 2 o 3 horas (RF-15)."""

    __tablename__ = "bloques_horario"
    __table_args__ = (
        UniqueConstraint(
            "curso_id",
            "dia_semana",
            "hora_inicio",
            name="uq_bloques_horario_curso_dia_inicio",
        ),
        CheckConstraint("dia_semana BETWEEN 1 AND 7", name="ck_bloques_horario_dia"),
        CheckConstraint(
            "TIME_TO_SEC(hora_fin) - TIME_TO_SEC(hora_inicio) IN (3600, 7200, 10800)",
            name="ck_bloques_horario_duracion",
        ),
        _opciones_tabla(
            "Horario semanal del curso: sesiones de 1, 2 o 3 horas (RF-15). "
            "El traslape lo valida la aplicacion"
        ),
    )

    id: Mapped[int] = mapped_column(ID_TIPO, primary_key=True, autoincrement=True)
    curso_id: Mapped[int] = mapped_column(
        ID_TIPO, _fk("cursos.id", "fk_bloques_horario_cursos"), nullable=False
    )
    dia_semana: Mapped[int] = mapped_column(
        TINYINT_SIN_SIGNO,
        nullable=False,
        comment="1 = lunes ... 7 = domingo (ISO 8601)",
    )
    hora_inicio: Mapped[dt.time] = mapped_column(Time, nullable=False)
    hora_fin: Mapped[dt.time] = mapped_column(Time, nullable=False)

    curso: Mapped[Curso] = relationship(back_populates="bloques_horario")


class SesionClase(db.Model):
    """Calendario de sesiones de cada curso (RF-19)."""

    __tablename__ = "sesiones_clase"
    __table_args__ = (
        UniqueConstraint(
            "curso_id",
            "fecha",
            "hora_inicio",
            name="uq_sesiones_clase_curso_fecha_inicio",
        ),
        Index("ix_sesiones_clase_registrador", "asistencia_registrada_por_usuario_id"),
        CheckConstraint(
            "TIME_TO_SEC(hora_fin) - TIME_TO_SEC(hora_inicio) IN (3600, 7200, 10800)",
            name="ck_sesiones_clase_duracion",
        ),
        CheckConstraint(
            "(asistencia_registrada_en IS NULL) = "
            "(asistencia_registrada_por_usuario_id IS NULL)",
            name="ck_sesiones_clase_registro",
        ),
        _opciones_tabla(
            "Calendario de sesiones de cada curso, generado desde horario, "
            "periodo y festivos (RF-19)"
        ),
    )

    id: Mapped[int] = mapped_column(ID_TIPO, primary_key=True, autoincrement=True)
    curso_id: Mapped[int] = mapped_column(
        ID_TIPO, _fk("cursos.id", "fk_sesiones_clase_cursos"), nullable=False
    )
    fecha: Mapped[dt.date] = mapped_column(Date, nullable=False)
    hora_inicio: Mapped[dt.time] = mapped_column(Time, nullable=False)
    hora_fin: Mapped[dt.time] = mapped_column(Time, nullable=False)
    # Columna calculada por la base de datos (VIRTUAL): solo lectura.
    duracion_horas: Mapped[Optional[int]] = mapped_column(
        TINYINT_SIN_SIGNO,
        Computed(
            "CAST((TIME_TO_SEC(hora_fin) - TIME_TO_SEC(hora_inicio)) / 3600 "
            "AS UNSIGNED)",
            persisted=False,
        ),
        comment="Calculada: horas que se cargan a cada ausente (RF-28)",
    )
    asistencia_registrada_en: Mapped[Optional[dt.datetime]] = mapped_column(
        DateTime,
        nullable=True,
        comment=(
            "Marca que el profesor registro la asistencia, aunque no haya "
            "ausentes (RF-30)"
        ),
    )
    asistencia_registrada_por_usuario_id: Mapped[Optional[int]] = mapped_column(
        ID_TIPO, _fk("usuarios.id", "fk_sesiones_clase_usuarios"), nullable=True
    )

    curso: Mapped[Curso] = relationship(back_populates="sesiones_clase")
    asistencia_registrada_por: Mapped[Optional[Usuario]] = relationship()
    ausencias: Mapped[list[Ausencia]] = relationship(back_populates="sesion_clase")


class ConfiguracionAlerta(db.Model):
    """Umbrales de alerta versionados; la vigente es la mas reciente (RF-20)."""

    __tablename__ = "configuraciones_alerta"
    __table_args__ = (
        Index("ix_configuraciones_alerta_vigente_desde", "vigente_desde"),
        Index("ix_configuraciones_alerta_creador", "creado_por_usuario_id"),
        CheckConstraint(
            "nota_aprobacion BETWEEN 1.0 AND 5.0",
            name="ck_configuraciones_alerta_nota",
        ),
        CheckConstraint(
            "umbral_amarillo_inasistencia > 0 AND umbral_amarillo_inasistencia "
            "< limite_perdida_inasistencia AND limite_perdida_inasistencia <= 100",
            name="ck_configuraciones_alerta_porcentajes",
        ),
        CheckConstraint(
            "nota_amarilla_minima BETWEEN 1.0 AND 5.0 AND nota_amarilla_maxima "
            "BETWEEN 1.0 AND 5.0 AND nota_amarilla_minima <= nota_amarilla_maxima",
            name="ck_configuraciones_alerta_rango_amarillo",
        ),
        _opciones_tabla(
            "Umbrales de alerta versionados: cada cambio es una fila nueva; "
            "la vigente es la mas reciente (RF-20)"
        ),
    )

    id: Mapped[int] = mapped_column(ID_TIPO, primary_key=True, autoincrement=True)
    nota_aprobacion: Mapped[Decimal] = mapped_column(
        Numeric(2, 1), nullable=False, server_default=text("3.0")
    )
    limite_perdida_inasistencia: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        server_default=text("30.00"),
        comment="Porcentaje; se pierde al superarlo",
    )
    umbral_amarillo_inasistencia: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        server_default=text("20.00"),
        comment="Porcentaje; tambien aplica al ritmo de inasistencia",
    )
    nota_amarilla_minima: Mapped[Decimal] = mapped_column(
        Numeric(2, 1), nullable=False, server_default=text("3.0")
    )
    nota_amarilla_maxima: Mapped[Decimal] = mapped_column(
        Numeric(2, 1), nullable=False, server_default=text("3.4")
    )
    vigente_desde: Mapped[dt.datetime] = mapped_column(
        DateTime, nullable=False, server_default=_AHORA
    )
    creado_por_usuario_id: Mapped[Optional[int]] = mapped_column(
        ID_TIPO,
        _fk("usuarios.id", "fk_configuraciones_alerta_usuarios"),
        nullable=True,
        comment="NULL = configuracion inicial del sistema",
    )

    creado_por: Mapped[Optional[Usuario]] = relationship()


# ===========================================================================
# E3. ESTUDIANTES E INSCRIPCIONES (RF-21 a RF-25)
# ===========================================================================


class EstadoEstudiante(db.Model):
    """Catalogo de estados del estudiante (RF-22)."""

    __tablename__ = "estados_estudiante"
    __table_args__ = (
        UniqueConstraint("codigo", name="uq_estados_estudiante_codigo"),
        UniqueConstraint("nombre", name="uq_estados_estudiante_nombre"),
        _opciones_tabla(
            "Catalogo: activo, graduado, retirado formal, aplazo semestre, "
            "cancelado (RF-22)"
        ),
    )

    id: Mapped[int] = mapped_column(ID_TIPO, primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(String(30), nullable=False)
    nombre: Mapped[str] = mapped_column(String(50), nullable=False)


class Estudiante(db.Model):
    """Estudiantes. Nunca se eliminan: se maneja su historial de estados (RF-21)."""

    __tablename__ = "estudiantes"
    __table_args__ = (
        UniqueConstraint("codigo", name="uq_estudiantes_codigo"),
        Index("ix_estudiantes_nombres", "nombres"),
        Index("ix_estudiantes_periodo_ingreso", "periodo_ingreso"),
        Index("ix_estudiantes_programa", "programa_academico_id"),
        CheckConstraint(
            "periodo_ingreso REGEXP '^[0-9]{4}-[12]$'",
            name="ck_estudiantes_periodo_ingreso",
        ),
        _opciones_tabla(
            "Estudiantes. Nunca se eliminan: su situacion se maneja con el "
            "historial de estados (RF-21)"
        ),
    )

    id: Mapped[int] = mapped_column(ID_TIPO, primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Codigo estudiantil: identificacion del estudiante en PLASEA",
    )
    nombres: Mapped[str] = mapped_column(String(150), nullable=False)
    correo: Mapped[str] = mapped_column(String(254), nullable=False)
    programa_academico_id: Mapped[int] = mapped_column(
        ID_TIPO,
        _fk("programas_academicos.id", "fk_estudiantes_programas_academicos"),
        nullable=False,
    )
    periodo_ingreso: Mapped[str] = mapped_column(
        String(6),
        nullable=False,
        comment=(
            "Cohorte (ejemplo 2022-1). Texto y no FK: puede ser anterior a los "
            "periodos registrados"
        ),
    )
    creado_en: Mapped[dt.datetime] = _creado_en()
    actualizado_en: Mapped[dt.datetime] = _actualizado_en()

    programa_academico: Mapped[ProgramaAcademico] = relationship()
    historial_estados: Mapped[list[HistorialEstadoEstudiante]] = relationship(
        back_populates="estudiante",
        order_by="(HistorialEstadoEstudiante.fecha_efectiva, "
        "HistorialEstadoEstudiante.id)",
    )
    matriculas: Mapped[list[MatriculaPeriodo]] = relationship(
        back_populates="estudiante"
    )


class HistorialEstadoEstudiante(db.Model):
    """Historial de estados; el actual es el de fecha_efectiva mas reciente (RF-22)."""

    __tablename__ = "historial_estados_estudiante"
    __table_args__ = (
        Index(
            "ix_historial_estados_estudiante_fecha", "estudiante_id", "fecha_efectiva"
        ),
        Index("ix_historial_estados_estudiante_estado", "estado_estudiante_id"),
        Index(
            "ix_historial_estados_estudiante_registrador", "registrado_por_usuario_id"
        ),
        _opciones_tabla(
            "Historial de estados del estudiante; el estado actual es el de "
            "fecha_efectiva mas reciente (RF-22)"
        ),
    )

    id: Mapped[int] = mapped_column(ID_TIPO, primary_key=True, autoincrement=True)
    estudiante_id: Mapped[int] = mapped_column(
        ID_TIPO,
        _fk("estudiantes.id", "fk_historial_estados_estudiantes"),
        nullable=False,
    )
    estado_estudiante_id: Mapped[int] = mapped_column(
        ID_TIPO,
        _fk("estados_estudiante.id", "fk_historial_estados_estados"),
        nullable=False,
    )
    fecha_efectiva: Mapped[dt.date] = mapped_column(Date, nullable=False)
    registrado_por_usuario_id: Mapped[int] = mapped_column(
        ID_TIPO,
        _fk("usuarios.id", "fk_historial_estados_usuarios"),
        nullable=False,
    )
    creado_en: Mapped[dt.datetime] = _creado_en()

    estudiante: Mapped[Estudiante] = relationship(back_populates="historial_estados")
    estado_estudiante: Mapped[EstadoEstudiante] = relationship()
    registrado_por: Mapped[Usuario] = relationship()


class MatriculaPeriodo(db.Model):
    """Participacion de un estudiante en un periodo (base de RF-49 a RF-53)."""

    __tablename__ = "matriculas_periodo"
    __table_args__ = (
        UniqueConstraint(
            "estudiante_id",
            "periodo_academico_id",
            name="uq_matriculas_periodo_estudiante_periodo",
        ),
        UniqueConstraint(
            "id", "periodo_academico_id", name="uq_matriculas_periodo_id_periodo"
        ),
        Index(
            "ix_matriculas_periodo_periodo_semestre",
            "periodo_academico_id",
            "semestre_cursado",
        ),
        CheckConstraint(
            "semestre_cursado BETWEEN 1 AND 10",
            name="ck_matriculas_periodo_semestre",
        ),
        _opciones_tabla(
            "Participacion de un estudiante en un periodo con su semestre "
            "cursado: base de RF-49 a RF-53"
        ),
    )

    id: Mapped[int] = mapped_column(ID_TIPO, primary_key=True, autoincrement=True)
    estudiante_id: Mapped[int] = mapped_column(
        ID_TIPO,
        _fk("estudiantes.id", "fk_matriculas_periodo_estudiantes"),
        nullable=False,
    )
    periodo_academico_id: Mapped[int] = mapped_column(
        ID_TIPO,
        _fk("periodos_academicos.id", "fk_matriculas_periodo_periodos"),
        nullable=False,
    )
    semestre_cursado: Mapped[int] = mapped_column(
        TINYINT_SIN_SIGNO,
        nullable=False,
        comment=(
            "Semestre de la carrera que cursa en el periodo, 1 a 10 (RF-23, RF-51)"
        ),
    )
    creado_en: Mapped[dt.datetime] = _creado_en()
    actualizado_en: Mapped[dt.datetime] = _actualizado_en()

    estudiante: Mapped[Estudiante] = relationship(back_populates="matriculas")
    periodo_academico: Mapped[PeriodoAcademico] = relationship()
    inscripciones: Mapped[list[Inscripcion]] = relationship(
        back_populates="matricula_periodo",
        primaryjoin="MatriculaPeriodo.id == Inscripcion.matricula_periodo_id",
        foreign_keys="Inscripcion.matricula_periodo_id",
    )


class Inscripcion(db.Model):
    """Inscripcion de un estudiante (via su matricula del periodo) en un curso (RF-23).

    ``periodo_academico_id`` es una columna de consistencia que participa en las
    dos llaves foraneas compuestas: la aplicacion debe asignarla explicitamente
    con el periodo de la matricula y del curso.
    """

    __tablename__ = "inscripciones"
    __table_args__ = (
        UniqueConstraint(
            "matricula_periodo_id", "curso_id", name="uq_inscripciones_matricula_curso"
        ),
        Index(
            "ix_inscripciones_matricula_periodo",
            "matricula_periodo_id",
            "periodo_academico_id",
        ),
        Index("ix_inscripciones_curso_periodo", "curso_id", "periodo_academico_id"),
        ForeignKeyConstraint(
            ["matricula_periodo_id", "periodo_academico_id"],
            ["matriculas_periodo.id", "matriculas_periodo.periodo_academico_id"],
            name="fk_inscripciones_matriculas_periodo",
            **_RESTRICT,
        ),
        ForeignKeyConstraint(
            ["curso_id", "periodo_academico_id"],
            ["cursos.id", "cursos.periodo_academico_id"],
            name="fk_inscripciones_cursos",
            **_RESTRICT,
        ),
        _opciones_tabla(
            "Inscripcion de un estudiante (via su matricula del periodo) en un "
            "curso (RF-23)"
        ),
    )

    id: Mapped[int] = mapped_column(ID_TIPO, primary_key=True, autoincrement=True)
    matricula_periodo_id: Mapped[int] = mapped_column(ID_TIPO, nullable=False)
    curso_id: Mapped[int] = mapped_column(ID_TIPO, nullable=False)
    periodo_academico_id: Mapped[int] = mapped_column(
        ID_TIPO,
        nullable=False,
        comment=(
            "Columna de consistencia: matricula y curso deben ser del mismo periodo"
        ),
    )
    retirada_en: Mapped[Optional[dt.date]] = mapped_column(
        Date,
        nullable=True,
        comment="Retiro del curso; la fila se conserva (RF-23)",
    )
    creado_en: Mapped[dt.datetime] = _creado_en()
    actualizado_en: Mapped[dt.datetime] = _actualizado_en()

    matricula_periodo: Mapped[MatriculaPeriodo] = relationship(
        back_populates="inscripciones",
        primaryjoin="MatriculaPeriodo.id == Inscripcion.matricula_periodo_id",
        foreign_keys=[matricula_periodo_id],
    )
    curso: Mapped[Curso] = relationship(
        back_populates="inscripciones",
        primaryjoin="Curso.id == Inscripcion.curso_id",
        foreign_keys=[curso_id],
    )
    notas_corte: Mapped[list[NotaCorte]] = relationship(back_populates="inscripcion")
    ausencias: Mapped[list[Ausencia]] = relationship(back_populates="inscripcion")
    alertas: Mapped[list[Alerta]] = relationship(back_populates="inscripcion")


# ===========================================================================
# E4 y E5. REGISTRO DE ASISTENCIA Y NOTAS, CIERRE DE CORTES (RF-26 a RF-39)
# ===========================================================================


class RegistroCursoCorte(db.Model):
    """Estado del registro de un curso en un corte (RF-26, RF-30, RF-35, RF-36)."""

    __tablename__ = "registros_curso_corte"
    __table_args__ = (
        UniqueConstraint(
            "curso_id", "corte_id", name="uq_registros_curso_corte_curso_corte"
        ),
        Index("ix_registros_curso_corte_corte_estado", "corte_id", "estado"),
        Index("ix_registros_curso_corte_enviador", "enviado_por_usuario_id"),
        CheckConstraint(
            "estado IN ('pendiente','enviado','cerrado','sin_registro')",
            name="ck_registros_curso_corte_estado",
        ),
        CheckConstraint(
            "(estado IN ('enviado','cerrado')) = (enviado_en IS NOT NULL) AND "
            "((enviado_en IS NULL) = (enviado_por_usuario_id IS NULL))",
            name="ck_registros_curso_corte_envio",
        ),
        _opciones_tabla(
            "Estado del registro de un curso en un corte: borrador a envio a "
            "cierre (RF-26, RF-30, RF-35, RF-36)"
        ),
    )

    id: Mapped[int] = mapped_column(ID_TIPO, primary_key=True, autoincrement=True)
    curso_id: Mapped[int] = mapped_column(
        ID_TIPO, _fk("cursos.id", "fk_registros_curso_corte_cursos"), nullable=False
    )
    corte_id: Mapped[int] = mapped_column(
        ID_TIPO, _fk("cortes.id", "fk_registros_curso_corte_cortes"), nullable=False
    )
    estado: Mapped[str] = mapped_column(
        String(15),
        nullable=False,
        server_default=text("'pendiente'"),
        comment="pendiente | enviado | cerrado | sin_registro",
    )
    enviado_en: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)
    enviado_por_usuario_id: Mapped[Optional[int]] = mapped_column(
        ID_TIPO,
        _fk("usuarios.id", "fk_registros_curso_corte_usuarios"),
        nullable=True,
    )
    creado_en: Mapped[dt.datetime] = _creado_en()
    actualizado_en: Mapped[dt.datetime] = _actualizado_en()

    curso: Mapped[Curso] = relationship()
    corte: Mapped[Corte] = relationship()
    enviado_por: Mapped[Optional[Usuario]] = relationship()
    reaperturas: Mapped[list[ReaperturaCurso]] = relationship(
        back_populates="registro_curso_corte"
    )


class ReaperturaCurso(db.Model):
    """Reaperturas excepcionales por curso y corte (RF-38, RF-39)."""

    __tablename__ = "reaperturas_curso"
    __table_args__ = (
        UniqueConstraint(
            "registro_curso_corte_id",
            "vigente_marca",
            name="uq_reaperturas_curso_registro_vigente",
        ),
        Index("ix_reaperturas_curso_apertura", "abierta_por_usuario_id"),
        Index("ix_reaperturas_curso_cierre", "cerrada_por_usuario_id"),
        CheckConstraint(
            "CHAR_LENGTH(TRIM(motivo)) > 0", name="ck_reaperturas_curso_motivo"
        ),
        CheckConstraint(
            "(cerrada_en IS NULL) = (cerrada_por_usuario_id IS NULL)",
            name="ck_reaperturas_curso_cierre",
        ),
        _opciones_tabla(
            "Reaperturas excepcionales por curso y corte, con motivo obligatorio "
            "(RF-38, RF-39)"
        ),
    )

    id: Mapped[int] = mapped_column(ID_TIPO, primary_key=True, autoincrement=True)
    registro_curso_corte_id: Mapped[int] = mapped_column(
        ID_TIPO,
        _fk("registros_curso_corte.id", "fk_reaperturas_curso_registros"),
        nullable=False,
    )
    motivo: Mapped[str] = mapped_column(String(500), nullable=False)
    abierta_por_usuario_id: Mapped[int] = mapped_column(
        ID_TIPO,
        _fk("usuarios.id", "fk_reaperturas_curso_usuarios_apertura"),
        nullable=False,
    )
    abierta_en: Mapped[dt.datetime] = mapped_column(
        DateTime, nullable=False, server_default=_AHORA
    )
    cerrada_por_usuario_id: Mapped[Optional[int]] = mapped_column(
        ID_TIPO,
        _fk("usuarios.id", "fk_reaperturas_curso_usuarios_cierre"),
        nullable=True,
    )
    cerrada_en: Mapped[Optional[dt.datetime]] = mapped_column(
        DateTime, nullable=True, comment="NULL = reapertura vigente (RF-39)"
    )
    # Columna calculada por la base de datos (PERSISTENT): solo lectura.
    vigente_marca: Mapped[Optional[int]] = mapped_column(
        TINYINT_CON_SIGNO,
        Computed("IF(cerrada_en IS NULL, 1, NULL)", persisted=True),
        comment=(
            "Calculada: 1 si vigente. UNIQUE garantiza una sola reapertura "
            "vigente por registro"
        ),
    )

    registro_curso_corte: Mapped[RegistroCursoCorte] = relationship(
        back_populates="reaperturas"
    )
    abierta_por: Mapped[Usuario] = relationship(foreign_keys=[abierta_por_usuario_id])
    cerrada_por: Mapped[Optional[Usuario]] = relationship(
        foreign_keys=[cerrada_por_usuario_id]
    )


class NotaCorte(db.Model):
    """Nota consolidada de un estudiante en un corte (RF-29)."""

    __tablename__ = "notas_corte"
    __table_args__ = (
        UniqueConstraint(
            "inscripcion_id", "corte_id", name="uq_notas_corte_inscripcion_corte"
        ),
        Index("ix_notas_corte_corte", "corte_id"),
        Index("ix_notas_corte_registrador", "registrada_por_usuario_id"),
        CheckConstraint("nota BETWEEN 1.0 AND 5.0", name="ck_notas_corte_nota"),
        _opciones_tabla(
            "Nota consolidada de un estudiante en un corte; la fila existe solo "
            "si hay nota (RF-29)"
        ),
    )

    id: Mapped[int] = mapped_column(ID_TIPO, primary_key=True, autoincrement=True)
    inscripcion_id: Mapped[int] = mapped_column(
        ID_TIPO,
        _fk("inscripciones.id", "fk_notas_corte_inscripciones"),
        nullable=False,
    )
    corte_id: Mapped[int] = mapped_column(
        ID_TIPO, _fk("cortes.id", "fk_notas_corte_cortes"), nullable=False
    )
    nota: Mapped[Decimal] = mapped_column(
        Numeric(2, 1),
        nullable=False,
        comment="Escala 1,0 a 5,0 con un decimal (RF-29)",
    )
    registrada_por_usuario_id: Mapped[int] = mapped_column(
        ID_TIPO, _fk("usuarios.id", "fk_notas_corte_usuarios"), nullable=False
    )
    creado_en: Mapped[dt.datetime] = _creado_en()
    actualizado_en: Mapped[dt.datetime] = _actualizado_en()

    inscripcion: Mapped[Inscripcion] = relationship(back_populates="notas_corte")
    corte: Mapped[Corte] = relationship()
    registrada_por: Mapped[Usuario] = relationship()
    historial: Mapped[list[HistorialNota]] = relationship(
        back_populates="nota_corte", order_by="HistorialNota.creado_en"
    )


class Ausencia(db.Model):
    """Solo se guardan los ausentes; sin fila = presente (RF-28)."""

    __tablename__ = "ausencias"
    __table_args__ = (
        UniqueConstraint(
            "sesion_clase_id", "inscripcion_id", name="uq_ausencias_sesion_inscripcion"
        ),
        Index("ix_ausencias_inscripcion_ausente", "inscripcion_id", "ausente"),
        Index("ix_ausencias_registrador", "registrada_por_usuario_id"),
        CheckConstraint("ausente IN (0,1)", name="ck_ausencias_ausente"),
        _opciones_tabla(
            "Solo se guardan los ausentes; quien no tiene fila estuvo presente "
            "(RF-28)"
        ),
    )

    id: Mapped[int] = mapped_column(ID_TIPO, primary_key=True, autoincrement=True)
    sesion_clase_id: Mapped[int] = mapped_column(
        ID_TIPO,
        _fk("sesiones_clase.id", "fk_ausencias_sesiones_clase"),
        nullable=False,
    )
    inscripcion_id: Mapped[int] = mapped_column(
        ID_TIPO,
        _fk("inscripciones.id", "fk_ausencias_inscripciones"),
        nullable=False,
    )
    ausente: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("1"),
        comment="1 = ausente; 0 = ausencia corregida (la fila no se elimina)",
    )
    registrada_por_usuario_id: Mapped[int] = mapped_column(
        ID_TIPO, _fk("usuarios.id", "fk_ausencias_usuarios"), nullable=False
    )
    creado_en: Mapped[dt.datetime] = _creado_en()
    actualizado_en: Mapped[dt.datetime] = _actualizado_en()

    sesion_clase: Mapped[SesionClase] = relationship(back_populates="ausencias")
    inscripcion: Mapped[Inscripcion] = relationship(back_populates="ausencias")
    registrada_por: Mapped[Usuario] = relationship()
    historial: Mapped[list[HistorialAusencia]] = relationship(
        back_populates="ausencia", order_by="HistorialAusencia.creado_en"
    )


class HistorialNota(db.Model):
    """Correcciones de notas (RF-31, RF-33). Inmutable (trigger en la base)."""

    __tablename__ = "historial_notas"
    __table_args__ = (
        Index("ix_historial_notas_nota_corte", "nota_corte_id"),
        Index("ix_historial_notas_creado_en", "creado_en"),
        Index("ix_historial_notas_usuario", "usuario_id"),
        Index("ix_historial_notas_reapertura", "reapertura_curso_id"),
        CheckConstraint(
            "nota_anterior <> nota_nueva", name="ck_historial_notas_cambio"
        ),
        CheckConstraint(
            "CHAR_LENGTH(TRIM(motivo)) > 0", name="ck_historial_notas_motivo"
        ),
        _opciones_tabla(
            "Correcciones de notas: valor anterior, nuevo, motivo, usuario y "
            "fecha (RF-31, RF-33). Inmutable"
        ),
    )

    id: Mapped[int] = mapped_column(ID_TIPO, primary_key=True, autoincrement=True)
    nota_corte_id: Mapped[int] = mapped_column(
        ID_TIPO,
        _fk("notas_corte.id", "fk_historial_notas_notas_corte"),
        nullable=False,
    )
    nota_anterior: Mapped[Decimal] = mapped_column(Numeric(2, 1), nullable=False)
    nota_nueva: Mapped[Decimal] = mapped_column(Numeric(2, 1), nullable=False)
    motivo: Mapped[str] = mapped_column(String(500), nullable=False)
    usuario_id: Mapped[int] = mapped_column(
        ID_TIPO, _fk("usuarios.id", "fk_historial_notas_usuarios"), nullable=False
    )
    reapertura_curso_id: Mapped[Optional[int]] = mapped_column(
        ID_TIPO,
        _fk("reaperturas_curso.id", "fk_historial_notas_reaperturas"),
        nullable=True,
        comment=("Si la correccion se hizo en una reapertura excepcional (RF-38)"),
    )
    creado_en: Mapped[dt.datetime] = _creado_en()

    nota_corte: Mapped[NotaCorte] = relationship(back_populates="historial")
    usuario: Mapped[Usuario] = relationship()
    reapertura_curso: Mapped[Optional[ReaperturaCurso]] = relationship()


class HistorialAusencia(db.Model):
    """Correcciones de asistencia (RF-31, RF-33). Inmutable (trigger en la base)."""

    __tablename__ = "historial_ausencias"
    __table_args__ = (
        Index("ix_historial_ausencias_ausencia", "ausencia_id"),
        Index("ix_historial_ausencias_creado_en", "creado_en"),
        Index("ix_historial_ausencias_usuario", "usuario_id"),
        Index("ix_historial_ausencias_reapertura", "reapertura_curso_id"),
        CheckConstraint(
            "ausente_anterior IN (0,1) AND ausente_nuevo IN (0,1) AND "
            "ausente_anterior <> ausente_nuevo",
            name="ck_historial_ausencias_valores",
        ),
        CheckConstraint(
            "CHAR_LENGTH(TRIM(motivo)) > 0", name="ck_historial_ausencias_motivo"
        ),
        _opciones_tabla("Correcciones de asistencia (RF-31, RF-33). Inmutable"),
    )

    id: Mapped[int] = mapped_column(ID_TIPO, primary_key=True, autoincrement=True)
    ausencia_id: Mapped[int] = mapped_column(
        ID_TIPO,
        _fk("ausencias.id", "fk_historial_ausencias_ausencias"),
        nullable=False,
    )
    ausente_anterior: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ausente_nuevo: Mapped[bool] = mapped_column(Boolean, nullable=False)
    motivo: Mapped[str] = mapped_column(String(500), nullable=False)
    usuario_id: Mapped[int] = mapped_column(
        ID_TIPO,
        _fk("usuarios.id", "fk_historial_ausencias_usuarios"),
        nullable=False,
    )
    reapertura_curso_id: Mapped[Optional[int]] = mapped_column(
        ID_TIPO,
        _fk("reaperturas_curso.id", "fk_historial_ausencias_reaperturas"),
        nullable=True,
    )
    creado_en: Mapped[dt.datetime] = _creado_en()

    ausencia: Mapped[Ausencia] = relationship(back_populates="historial")
    usuario: Mapped[Usuario] = relationship()
    reapertura_curso: Mapped[Optional[ReaperturaCurso]] = relationship()


# ===========================================================================
# E6. ALERTAS Y ANALITICA (RF-40 a RF-48)
# ===========================================================================


class Alerta(db.Model):
    """Resultado calculado por estudiante, curso y corte (RF-40 a RF-43)."""

    __tablename__ = "alertas"
    __table_args__ = (
        UniqueConstraint(
            "inscripcion_id", "corte_id", name="uq_alertas_inscripcion_corte"
        ),
        Index("ix_alertas_corte_estado", "corte_id", "estado_alerta"),
        Index("ix_alertas_configuracion", "configuracion_alerta_id"),
        CheckConstraint(
            "estado_alerta IN ('verde','amarilla','roja')", name="ck_alertas_estado"
        ),
        CheckConstraint(
            "motivo_nota IN (0,1) AND motivo_inasistencia IN (0,1)",
            name="ck_alertas_motivos",
        ),
        CheckConstraint(
            "(estado_alerta = 'verde') = (motivo_nota = 0 AND "
            "motivo_inasistencia = 0)",
            name="ck_alertas_coherencia_motivo",
        ),
        CheckConstraint("definitiva IN (0,1)", name="ck_alertas_definitiva"),
        CheckConstraint(
            "horas_ausentes <= horas_totales AND horas_dictadas <= horas_totales",
            name="ck_alertas_horas",
        ),
        _opciones_tabla(
            "Resultado calculado por estudiante, curso y corte. Copia controlada "
            "de datos derivados (ver modelo-datos.md)"
        ),
    )

    id: Mapped[int] = mapped_column(ID_TIPO, primary_key=True, autoincrement=True)
    inscripcion_id: Mapped[int] = mapped_column(
        ID_TIPO,
        _fk("inscripciones.id", "fk_alertas_inscripciones"),
        nullable=False,
    )
    corte_id: Mapped[int] = mapped_column(
        ID_TIPO, _fk("cortes.id", "fk_alertas_cortes"), nullable=False
    )
    configuracion_alerta_id: Mapped[int] = mapped_column(
        ID_TIPO,
        _fk("configuraciones_alerta.id", "fk_alertas_configuraciones_alerta"),
        nullable=False,
        comment="Version de umbrales con la que se calculo (RF-20)",
    )
    estado_alerta: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="verde | amarilla | roja (RF-43)"
    )
    motivo_nota: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0")
    )
    motivo_inasistencia: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0")
    )
    nota_corte: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(2, 1),
        nullable=True,
        comment="NULL si el estudiante no tiene nota en el corte",
    )
    nota_acumulada: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(4, 2),
        nullable=True,
        comment="RF-40: puede tener hasta dos decimales",
    )
    nota_requerida: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2),
        nullable=True,
        comment=(
            "RF-41: puede superar 5,0 (asignatura perdida por nota); NULL tras "
            "el ultimo corte"
        ),
    )
    horas_ausentes: Mapped[int] = mapped_column(
        SMALLINT_SIN_SIGNO, nullable=False, server_default=text("0")
    )
    horas_dictadas: Mapped[int] = mapped_column(
        SMALLINT_SIN_SIGNO, nullable=False, server_default=text("0")
    )
    horas_totales: Mapped[int] = mapped_column(
        SMALLINT_SIN_SIGNO, nullable=False, server_default=text("0")
    )
    porcentaje_inasistencia: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        server_default=text("0"),
        comment="Horas ausentes / horas totales (RF-42)",
    )
    porcentaje_ritmo: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2),
        nullable=True,
        comment=("Horas ausentes / horas dictadas; NULL si aun no hay horas dictadas"),
    )
    definitiva: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("0"),
        comment="0 = provisional; 1 = definitiva al cerrar el corte (RF-43)",
    )
    calculada_en: Mapped[dt.datetime] = mapped_column(
        DateTime, nullable=False, server_default=_AHORA
    )

    inscripcion: Mapped[Inscripcion] = relationship(back_populates="alertas")
    corte: Mapped[Corte] = relationship()
    configuracion_alerta: Mapped[ConfiguracionAlerta] = relationship()


# ===========================================================================
# E7. CONTINUIDAD Y DESERCION (RF-49 a RF-53)
# ===========================================================================


class CausaNoContinuidad(db.Model):
    """Lista fija de causas de no continuidad (RF-52)."""

    __tablename__ = "causas_no_continuidad"
    __table_args__ = (
        UniqueConstraint("codigo", name="uq_causas_no_continuidad_codigo"),
        UniqueConstraint("nombre", name="uq_causas_no_continuidad_nombre"),
        _opciones_tabla(
            "Lista fija: economica, academica, personal, laboral, otra (RF-52)"
        ),
    )

    id: Mapped[int] = mapped_column(ID_TIPO, primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(String(30), nullable=False)
    nombre: Mapped[str] = mapped_column(String(50), nullable=False)


class RegistroCausaNoContinuidad(db.Model):
    """Causa opcional con historial; la vigente es la ultima (RF-52)."""

    __tablename__ = "registros_causa_no_continuidad"
    __table_args__ = (
        Index("ix_registros_causa_matricula", "matricula_periodo_id", "id"),
        Index("ix_registros_causa_causa", "causa_no_continuidad_id"),
        Index("ix_registros_causa_registrador", "registrado_por_usuario_id"),
        _opciones_tabla(
            "Causa opcional con historial: cada cambio agrega una fila; la "
            "vigente es la ultima (RF-52)"
        ),
    )

    id: Mapped[int] = mapped_column(ID_TIPO, primary_key=True, autoincrement=True)
    matricula_periodo_id: Mapped[int] = mapped_column(
        ID_TIPO,
        _fk("matriculas_periodo.id", "fk_registros_causa_matriculas"),
        nullable=False,
        comment=("Participacion del estudiante en el periodo tras el cual no continuo"),
    )
    causa_no_continuidad_id: Mapped[int] = mapped_column(
        ID_TIPO,
        _fk("causas_no_continuidad.id", "fk_registros_causa_causas"),
        nullable=False,
    )
    registrado_por_usuario_id: Mapped[int] = mapped_column(
        ID_TIPO, _fk("usuarios.id", "fk_registros_causa_usuarios"), nullable=False
    )
    registrado_en: Mapped[dt.datetime] = mapped_column(
        DateTime, nullable=False, server_default=_AHORA
    )

    matricula_periodo: Mapped[MatriculaPeriodo] = relationship()
    causa_no_continuidad: Mapped[CausaNoContinuidad] = relationship()
    registrado_por: Mapped[Usuario] = relationship()


# ===========================================================================
# E11. BITACORA (RF-61)
# ===========================================================================


class TipoEventoBitacora(db.Model):
    """Catalogo de eventos que se registran (RF-61)."""

    __tablename__ = "tipos_evento_bitacora"
    __table_args__ = (
        UniqueConstraint("codigo", name="uq_tipos_evento_bitacora_codigo"),
        _opciones_tabla("Catalogo de eventos que se registran (RF-61)"),
    )

    id: Mapped[int] = mapped_column(ID_TIPO, primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(String(40), nullable=False)
    descripcion: Mapped[str] = mapped_column(String(150), nullable=False)


class Bitacora(db.Model):
    """Registro inmutable de eventos (RF-61). Solo insercion (trigger en la base)."""

    __tablename__ = "bitacora"
    __table_args__ = (
        Index("ix_bitacora_creado_en", "creado_en"),
        Index("ix_bitacora_usuario_fecha", "usuario_id", "creado_en"),
        Index("ix_bitacora_evento_fecha", "tipo_evento_id", "creado_en"),
        Index("ix_bitacora_entidad", "entidad", "entidad_id"),
        _opciones_tabla(
            "Registro inmutable de eventos con usuario, accion, objeto y "
            "fecha-hora (RF-61)"
        ),
    )

    id: Mapped[int] = mapped_column(ID_TIPO, primary_key=True, autoincrement=True)
    creado_en: Mapped[dt.datetime] = mapped_column(
        DATETIME_MILISEGUNDOS,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(3)"),
    )
    tipo_evento_id: Mapped[int] = mapped_column(
        ID_TIPO,
        _fk("tipos_evento_bitacora.id", "fk_bitacora_tipos_evento"),
        nullable=False,
    )
    usuario_id: Mapped[Optional[int]] = mapped_column(
        ID_TIPO,
        _fk("usuarios.id", "fk_bitacora_usuarios"),
        nullable=True,
        comment=("NULL = el Sistema, o un intento fallido con correo no registrado"),
    )
    entidad: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment=(
            "Nombre de la tabla afectada, sin FK a proposito: la bitacora debe "
            "sobrevivir a cualquier tabla"
        ),
    )
    entidad_id: Mapped[Optional[int]] = mapped_column(ID_TIPO, nullable=True)
    detalle: Mapped[Optional[str]] = mapped_column(
        String(1000),
        nullable=True,
        comment="Texto breve; nunca contrasenas, tokens ni datos sensibles",
    )

    tipo_evento: Mapped[TipoEventoBitacora] = relationship()
    usuario: Mapped[Optional[Usuario]] = relationship()


__all__ = [
    "db",
    "Rol",
    "Usuario",
    "TokenCuenta",
    "SesionUsuario",
    "ProgramaAcademico",
    "Asignatura",
    "PeriodoAcademico",
    "Corte",
    "Festivo",
    "Curso",
    "BloqueHorario",
    "SesionClase",
    "ConfiguracionAlerta",
    "EstadoEstudiante",
    "Estudiante",
    "HistorialEstadoEstudiante",
    "MatriculaPeriodo",
    "Inscripcion",
    "RegistroCursoCorte",
    "ReaperturaCurso",
    "NotaCorte",
    "Ausencia",
    "HistorialNota",
    "HistorialAusencia",
    "Alerta",
    "CausaNoContinuidad",
    "RegistroCausaNoContinuidad",
    "TipoEventoBitacora",
    "Bitacora",
]
