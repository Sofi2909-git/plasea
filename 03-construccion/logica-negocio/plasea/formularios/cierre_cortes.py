"""Formularios de la épica E5: cierre de cortes y reaperturas (RF-36 a RF-39)."""

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length


class FormularioAccion(FlaskForm):
    """Acción confirmada sin datos (cerrar corte o reapertura): aporta CSRF."""

    enviar = SubmitField("Confirmar")


class FormularioReapertura(FlaskForm):
    """Reapertura excepcional de un curso con motivo obligatorio (RF-38)."""

    motivo = TextAreaField(
        "Motivo de la reapertura",
        validators=[
            DataRequired("Escriba el motivo de la reapertura."),
            Length(
                min=10, max=500, message="El motivo debe tener de 10 a 500 caracteres."
            ),
        ],
        render_kw={"rows": 4, "maxlength": 500},
    )
    reabrir = SubmitField("Reabrir curso")
