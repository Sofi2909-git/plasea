"""Formularios de la épica E1: Acceso y cuentas (RF-01 a RF-12)."""

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import PasswordField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Length

MENSAJE_OBLIGATORIO = "Este campo es obligatorio."


class FormularioInicioSesion(FlaskForm):
    """Inicio de sesión con correo y contraseña (RF-01)."""

    correo = StringField(
        "Correo institucional",
        validators=[DataRequired(MENSAJE_OBLIGATORIO), Length(max=254)],
        render_kw={"autocomplete": "username", "inputmode": "email"},
    )
    contrasena = PasswordField(
        "Contraseña",
        validators=[DataRequired(MENSAJE_OBLIGATORIO)],
        render_kw={"autocomplete": "current-password"},
    )
    enviar = SubmitField("Iniciar sesión")


class FormularioSolicitudRestablecimiento(FlaskForm):
    """Solicitud del enlace de restablecimiento de contraseña (RF-06)."""

    correo = StringField(
        "Correo institucional",
        validators=[DataRequired(MENSAJE_OBLIGATORIO), Length(max=254)],
        render_kw={"autocomplete": "email", "inputmode": "email"},
    )
    enviar = SubmitField("Enviar enlace")


class FormularioNuevaContrasena(FlaskForm):
    """Definición de contraseña desde un enlace (RF-07 y RF-09)."""

    contrasena = PasswordField(
        "Nueva contraseña",
        validators=[DataRequired(MENSAJE_OBLIGATORIO)],
        render_kw={"autocomplete": "new-password"},
    )
    confirmacion = PasswordField(
        "Confirme la contraseña",
        validators=[DataRequired(MENSAJE_OBLIGATORIO)],
        render_kw={"autocomplete": "new-password"},
    )
    enviar = SubmitField("Guardar contraseña")


class FormularioCuenta(FlaskForm):
    """Creación y modificación de cuentas (RF-08 y RF-10)."""

    nombre_completo = StringField(
        "Nombre completo",
        validators=[DataRequired(MENSAJE_OBLIGATORIO), Length(min=3, max=150)],
        render_kw={"autocomplete": "off"},
    )
    correo = StringField(
        "Correo institucional",
        validators=[DataRequired(MENSAJE_OBLIGATORIO), Length(max=254)],
        render_kw={"autocomplete": "off", "inputmode": "email"},
    )
    rol = SelectField(
        "Rol", validators=[DataRequired("Seleccione un rol.")], choices=[]
    )
    enviar = SubmitField("Guardar")
