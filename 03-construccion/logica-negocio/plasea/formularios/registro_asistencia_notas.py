"""Formularios de la épica E4: registro de asistencia y notas (RF-28, RF-29).

Las listas de ausentes y de notas son dinámicas (un campo por estudiante), así
que se leen de ``request.form`` en la ruta; estos formularios aportan la
protección CSRF y el botón de envío. La validación real ocurre en el servicio.
"""

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import SubmitField


class FormularioAsistencia(FlaskForm):
    """Asistencia de una sesión: se marcan solo los ausentes (RF-28)."""

    guardar = SubmitField("Guardar asistencia")


class FormularioNotas(FlaskForm):
    """Planilla de notas de un corte, guardada como borrador (RF-29)."""

    guardar = SubmitField("Guardar borrador")
