"""Formularios de la épica E4: asistencia, notas, envío y correcciones (RF-28 a RF-31).

Las listas de ausentes y de notas son dinámicas (un campo por estudiante), así
que se leen de ``request.form`` en la ruta; estos formularios aportan la
protección CSRF y el botón de envío. La validación real ocurre en el servicio.
"""

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import SubmitField, TextAreaField
from wtforms.validators import Length


class FormularioAsistencia(FlaskForm):
    """Asistencia de una sesión: se marcan solo los ausentes (RF-28)."""

    guardar = SubmitField("Guardar asistencia")


class FormularioNotas(FlaskForm):
    """Planilla de notas de un corte, guardada como borrador (RF-29)."""

    guardar = SubmitField("Guardar borrador")


class FormularioEnvio(FlaskForm):
    """Envío del registro de un curso en un corte (RF-30)."""

    enviar = SubmitField("Enviar registro")


class FormularioCorreccion(FlaskForm):
    """Corrección con motivo de notas o asistencia (RF-31).

    Las notas nuevas y sus motivos llegan por estudiante en ``request.form``;
    el motivo de la asistencia es uno por sesión.
    """

    motivo = TextAreaField(
        "Motivo de la corrección",
        validators=[Length(max=500, message="El motivo admite hasta 500 caracteres.")],
        render_kw={"rows": 2, "maxlength": 500},
    )
    guardar = SubmitField("Guardar corrección")
