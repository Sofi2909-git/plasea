"""Formularios de la épica E2: Estructura académica (RF-13 a RF-20)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from flask_wtf import FlaskForm
from wtforms import (
    DateField,
    Field,
    FieldList,
    FormField,
    IntegerField,
    SelectField,
    StringField,
    SubmitField,
    TimeField,
)
from wtforms.form import Form
from wtforms.validators import DataRequired, InputRequired, Length, NumberRange
from wtforms.widgets import TextInput

MENSAJE_OBLIGATORIO = "Este campo es obligatorio."
MENSAJE_FECHA = "Escriba una fecha válida."


class DecimalComaField(Field):
    """Decimal que acepta coma o punto y se muestra con coma (formato colombiano)."""

    widget = TextInput()

    def __init__(self, label: str = "", validators: Any = None, **kwargs: Any) -> None:
        kwargs.setdefault("render_kw", {"inputmode": "decimal", "autocomplete": "off"})
        super().__init__(label, validators, **kwargs)

    def _value(self) -> str:
        """Texto que se muestra en el campo."""
        if self.raw_data:
            return self.raw_data[0]
        if self.data is None:
            return ""
        return format(self.data.normalize(), "f").replace(".", ",")

    def process_formdata(self, valuelist: list[str]) -> None:
        """Convierte el texto del usuario a ``Decimal``."""
        if not valuelist or not valuelist[0].strip():
            self.data = None
            return
        texto = valuelist[0].strip().replace(" ", "").replace(",", ".")
        try:
            self.data = Decimal(texto)
        except InvalidOperation as error:
            self.data = None
            raise ValueError("Escriba un número válido (por ejemplo 3,0).") from error


class FormularioAsignatura(FlaskForm):
    """Registro y modificación de asignaturas (RF-13)."""

    codigo = StringField(
        "Código",
        validators=[DataRequired(MENSAJE_OBLIGATORIO), Length(max=20)],
        render_kw={"autocomplete": "off", "placeholder": "Ej.: ISI501"},
    )
    nombre = StringField(
        "Nombre", validators=[DataRequired(MENSAJE_OBLIGATORIO), Length(max=150)]
    )
    programa_academico_id = SelectField(
        "Programa académico",
        coerce=int,
        validators=[DataRequired("Seleccione un programa.")],
        choices=[],
    )
    creditos = SelectField(
        "Créditos",
        coerce=int,
        choices=[(3, "3"), (4, "4")],
        validators=[InputRequired("Seleccione los créditos.")],
    )
    horas_semanales = IntegerField(
        "Horas semanales",
        validators=[
            InputRequired(MENSAJE_OBLIGATORIO),
            NumberRange(1, 20, "Escriba un valor entre 1 y 20."),
        ],
    )
    nivel = SelectField(
        "Nivel de la carrera",
        coerce=int,
        choices=[(n, str(n)) for n in range(1, 11)],
        validators=[InputRequired("Seleccione el nivel.")],
    )
    enviar = SubmitField("Guardar")


class FormularioPeriodo(FlaskForm):
    """Registro y modificación de períodos académicos (RF-16)."""

    identificador = StringField(
        "Identificador",
        validators=[DataRequired(MENSAJE_OBLIGATORIO), Length(max=6)],
        render_kw={"placeholder": "Ej.: 2026-2", "autocomplete": "off"},
    )
    fecha_inicio = DateField(
        "Fecha de inicio", validators=[InputRequired(MENSAJE_FECHA)]
    )
    fecha_fin = DateField("Fecha de fin", validators=[InputRequired(MENSAJE_FECHA)])
    enviar = SubmitField("Guardar")


class SubformularioCorte(Form):
    """Datos de un corte dentro del formulario de cortes (sin CSRF propio)."""

    numero = IntegerField("Corte")
    peso_porcentaje = DecimalComaField(
        "Peso (%)", validators=[InputRequired(MENSAJE_OBLIGATORIO)]
    )
    fecha_inicio = DateField("Inicio", validators=[InputRequired(MENSAJE_FECHA)])
    fecha_fin = DateField("Fin", validators=[InputRequired(MENSAJE_FECHA)])
    limite_carga = DateField(
        "Límite de carga", validators=[InputRequired(MENSAJE_FECHA)]
    )
    limite_correccion = DateField(
        "Límite de corrección", validators=[InputRequired(MENSAJE_FECHA)]
    )


class FormularioCortes(FlaskForm):
    """Definición de los 3 cortes de un período (RF-17)."""

    cortes = FieldList(FormField(SubformularioCorte), min_entries=3, max_entries=3)
    enviar = SubmitField("Guardar cortes")


class FormularioFestivo(FlaskForm):
    """Registro de un festivo del período (RF-18)."""

    fecha = DateField("Fecha del festivo", validators=[InputRequired(MENSAJE_FECHA)])
    enviar = SubmitField("Agregar festivo")


class FormularioCurso(FlaskForm):
    """Registro de un curso (RF-14)."""

    periodo_academico_id = SelectField(
        "Período", coerce=int, validators=[DataRequired("Seleccione un período.")]
    )
    asignatura_id = SelectField(
        "Asignatura",
        coerce=int,
        validators=[DataRequired("Seleccione una asignatura.")],
    )
    codigo = StringField(
        "Código del curso",
        validators=[DataRequired(MENSAJE_OBLIGATORIO), Length(max=10)],
        render_kw={"placeholder": "Ej.: T01", "autocomplete": "off"},
    )
    profesor_usuario_id = SelectField(
        "Docente", coerce=int, validators=[DataRequired("Seleccione el docente.")]
    )
    enviar = SubmitField("Guardar")


class FormularioEditarCurso(FlaskForm):
    """Modificación de código y docente de un curso (RF-14)."""

    codigo = StringField(
        "Código del curso",
        validators=[DataRequired(MENSAJE_OBLIGATORIO), Length(max=10)],
    )
    profesor_usuario_id = SelectField(
        "Docente", coerce=int, validators=[DataRequired("Seleccione el docente.")]
    )
    enviar = SubmitField("Guardar")


class FormularioBloque(FlaskForm):
    """Bloque del horario semanal de un curso (RF-15)."""

    dia_semana = SelectField(
        "Día", coerce=int, validators=[DataRequired("Seleccione el día.")], choices=[]
    )
    hora_inicio = TimeField(
        "Hora de inicio", validators=[InputRequired("Hora inválida.")]
    )
    hora_fin = TimeField("Hora de fin", validators=[InputRequired("Hora inválida.")])
    enviar = SubmitField("Agregar bloque")


class FormularioUmbrales(FlaskForm):
    """Umbrales de alerta (RF-20)."""

    nota_aprobacion = DecimalComaField(
        "Nota de aprobación", validators=[InputRequired(MENSAJE_OBLIGATORIO)]
    )
    limite_perdida_inasistencia = DecimalComaField(
        "Límite de pérdida por inasistencia (%)",
        validators=[InputRequired(MENSAJE_OBLIGATORIO)],
    )
    umbral_amarillo_inasistencia = DecimalComaField(
        "Umbral amarillo de inasistencia (%)",
        validators=[InputRequired(MENSAJE_OBLIGATORIO)],
    )
    nota_amarilla_minima = DecimalComaField(
        "Rango amarillo de nota: desde", validators=[InputRequired(MENSAJE_OBLIGATORIO)]
    )
    nota_amarilla_maxima = DecimalComaField(
        "Rango amarillo de nota: hasta", validators=[InputRequired(MENSAJE_OBLIGATORIO)]
    )
    enviar = SubmitField("Guardar nueva versión")
