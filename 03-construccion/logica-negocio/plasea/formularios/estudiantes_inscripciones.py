"""Formularios de la épica E3: estudiantes e inscripciones (RF-21 a RF-24)."""

from __future__ import annotations

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import DateField, IntegerField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, InputRequired, Length, NumberRange

MENSAJE_OBLIGATORIO = "Este campo es obligatorio."


class FormularioEstudiante(FlaskForm):
    """Registro y modificación de estudiantes (RF-21)."""

    codigo = StringField(
        "Código estudiantil",
        validators=[DataRequired(MENSAJE_OBLIGATORIO), Length(max=20)],
        render_kw={"autocomplete": "off"},
    )
    nombres = StringField(
        "Nombres y apellidos",
        validators=[DataRequired(MENSAJE_OBLIGATORIO), Length(max=150)],
        render_kw={"autocomplete": "off"},
    )
    correo = StringField(
        "Correo",
        validators=[DataRequired(MENSAJE_OBLIGATORIO), Length(max=254)],
        render_kw={"autocomplete": "off", "inputmode": "email"},
    )
    programa_academico_id = SelectField(
        "Programa académico",
        coerce=int,
        validators=[DataRequired("Seleccione un programa.")],
        choices=[],
    )
    periodo_ingreso = StringField(
        "Período de ingreso (cohorte)",
        validators=[DataRequired(MENSAJE_OBLIGATORIO), Length(max=6)],
        render_kw={"placeholder": "Ej.: 2024-1", "autocomplete": "off"},
    )
    fecha_estado_inicial = DateField(
        "Activo desde",
        validators=[InputRequired("Escriba una fecha válida.")],
    )
    enviar = SubmitField("Guardar")


class FormularioEstado(FlaskForm):
    """Registro de un estado del estudiante con su fecha efectiva (RF-22)."""

    estado = SelectField(
        "Nuevo estado", validators=[DataRequired("Seleccione el estado.")], choices=[]
    )
    fecha_efectiva = DateField(
        "Fecha efectiva", validators=[InputRequired("Escriba una fecha válida.")]
    )
    enviar = SubmitField("Registrar estado")


class FormularioInscripcion(FlaskForm):
    """Inscripción de un estudiante en un curso (RF-23)."""

    codigo_estudiante = StringField(
        "Código del estudiante",
        validators=[DataRequired(MENSAJE_OBLIGATORIO), Length(max=20)],
        render_kw={"autocomplete": "off"},
    )
    semestre_cursado = IntegerField(
        "Semestre que cursa",
        validators=[
            InputRequired(MENSAJE_OBLIGATORIO),
            NumberRange(1, 10, "Debe estar entre 1 y 10."),
        ],
    )
    enviar = SubmitField("Inscribir")


class FormularioImportacion(FlaskForm):
    """Archivo CSV de estudiantes e inscripciones (RF-24)."""

    archivo = FileField(
        "Archivo CSV",
        validators=[
            FileRequired("Seleccione el archivo CSV."),
            FileAllowed(["csv"], "El archivo debe tener extensión .csv."),
        ],
        render_kw={"accept": ".csv,text/csv"},
    )
    validar = SubmitField("Validar archivo")


class FormularioConfirmacion(FlaskForm):
    """Confirmación o cancelación de una carga ya validada (RF-24)."""

    confirmar = SubmitField("Guardar registros válidos")
