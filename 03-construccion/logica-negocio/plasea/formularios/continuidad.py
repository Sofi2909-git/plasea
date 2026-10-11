"""Formularios de la épica E7: continuidad y deserción (RF-52)."""

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import SelectField, SubmitField
from wtforms.validators import DataRequired


class FormularioCausa(FlaskForm):
    """Causa de no continuidad de la lista fija (RF-52)."""

    causa = SelectField(
        "Causa", validators=[DataRequired("Seleccione una causa.")], choices=[]
    )
    guardar = SubmitField("Guardar")
