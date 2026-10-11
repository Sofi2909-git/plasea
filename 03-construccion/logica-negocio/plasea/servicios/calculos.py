"""Cálculos académicos puros (RF-40 a RF-43), sin base de datos.

Las decisiones se toman con el valor exacto (``Decimal``), nunca con el
redondeado: 3,0 exacto aprueba y 2,95 no. El redondeo solo se aplica al
guardar o mostrar. Los umbrales llegan como parámetro desde la configuración
vigente (RF-20); aquí no hay umbrales fijos. La única constante es la nota
máxima de la escala (5,0), que define RF-29.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Optional, Protocol

NOTA_MAXIMA_ESCALA = Decimal("5.0")
NOTA_MINIMA_ESCALA = Decimal("1.0")
CIEN = Decimal("100")

ESTADO_VERDE = "verde"
ESTADO_AMARILLA = "amarilla"
ESTADO_ROJA = "roja"
SEVERIDAD = {ESTADO_ROJA: 0, ESTADO_AMARILLA: 1, ESTADO_VERDE: 2}


class Umbrales(Protocol):
    """Campos de ``configuraciones_alerta`` que usa el cálculo (RF-20)."""

    nota_aprobacion: Decimal
    limite_perdida_inasistencia: Decimal
    umbral_amarillo_inasistencia: Decimal
    nota_amarilla_minima: Decimal
    nota_amarilla_maxima: Decimal


@dataclass(frozen=True)
class ResultadoAlerta:
    """Estado de alerta de un estudiante en una asignatura y corte (RF-43)."""

    estado: str
    motivo_nota: bool
    motivo_inasistencia: bool
    nota_corte: Optional[Decimal]
    nota_acumulada: Optional[Decimal]
    nota_requerida: Optional[Decimal]
    porcentaje_inasistencia: Decimal
    porcentaje_ritmo: Optional[Decimal]
    perdida_por_nota: bool
    aprobada_por_nota: bool

    @property
    def motivo(self) -> Optional[str]:
        """``nota``, ``inasistencia``, ``ambos`` o ``None`` si está en verde."""
        if self.motivo_nota and self.motivo_inasistencia:
            return "ambos"
        if self.motivo_nota:
            return "nota"
        if self.motivo_inasistencia:
            return "inasistencia"
        return None


def redondear(valor: Optional[Decimal], decimales: int = 2) -> Optional[Decimal]:
    """Redondeo comercial solo para guardar o mostrar (nunca para decidir)."""
    # Responsable: Islender Arturo Alfonso
    # RF-40
    if valor is None:
        return None
    return valor.quantize(Decimal(1).scaleb(-decimales), rounding=ROUND_HALF_UP)


def nota_acumulada(
    notas_y_pesos: Iterable[tuple[Optional[Decimal], Decimal]],
) -> Optional[Decimal]:
    """Suma de cada nota de corte por su peso (RF-40).

    Args:
        notas_y_pesos: pares (nota del corte o ``None``, peso en porcentaje).

    Returns:
        La acumulada (parcial si faltan cortes), o ``None`` si no hay notas.
        Ejemplo: 3,0, 2,0 y 4,0 con 30 %, 30 % y 40 % dan 3,1.
    """
    # Responsable: Islender Arturo Alfonso
    # RF-40
    total = Decimal("0")
    hay_nota = False
    for nota, peso in notas_y_pesos:
        if nota is None:
            continue
        hay_nota = True
        total += Decimal(nota) * Decimal(peso) / CIEN
    return total if hay_nota else None


def nota_requerida(
    nota_aprobacion: Decimal, acumulada_parcial: Decimal, peso_restante: Decimal
) -> Optional[Decimal]:
    """Nota mínima en los cortes restantes para aprobar (RF-41).

    ``peso_restante`` en porcentaje (70 tras el corte 1). Sin cortes restantes
    devuelve ``None``. Ejemplo: tras el corte 1 con 2,0, (3,0 − 0,6) / 0,7 = 3,43.
    """
    # Responsable: Islender Arturo Alfonso
    # RF-41
    if peso_restante <= 0:
        return None
    return (Decimal(nota_aprobacion) - Decimal(acumulada_parcial)) / (
        Decimal(peso_restante) / CIEN
    )


def porcentaje(parte: int, total: int) -> Optional[Decimal]:
    """Porcentaje exacto ``parte / total``; ``None`` si el total es 0 (RF-42)."""
    # Responsable: Islender Arturo Alfonso
    # RF-42
    if not total:
        return None
    return Decimal(parte) * CIEN / Decimal(total)


def evaluar_alerta(
    umbrales: Umbrales,
    notas_y_pesos: list[tuple[Optional[Decimal], Decimal]],
    peso_restante: Decimal,
    horas_ausentes: int,
    horas_totales: int,
    horas_dictadas: int,
) -> ResultadoAlerta:
    """Determina el estado de alerta y su motivo tras un corte (RF-40 a RF-43).

    Args:
        umbrales: configuración vigente de RF-20.
        notas_y_pesos: notas de los cortes 1..k (la última es la del corte k).
        peso_restante: suma de los pesos de los cortes posteriores a k (%).
        horas_ausentes: horas de ausencia hasta la fecha de referencia.
        horas_totales: horas del curso en todo el período.
        horas_dictadas: horas de clase ya dictadas a la fecha de referencia.

    Reglas (RF-43):
        - Roja: nota de corte < nota de aprobación, inasistencia acumulada >
          límite de pérdida o nota requerida > 5,0.
        - Amarilla: nota de corte en el rango amarillo, inasistencia
          acumulada ≥ umbral amarillo o ritmo ≥ umbral amarillo.
        - Verde: en los demás casos.
    """
    # Responsable: Islender Arturo Alfonso
    # RF-43
    nota_corte = notas_y_pesos[-1][0] if notas_y_pesos else None
    acumulada = nota_acumulada(notas_y_pesos)
    requerida = nota_requerida(
        umbrales.nota_aprobacion, acumulada or Decimal("0"), peso_restante
    )
    if acumulada is None and requerida is not None:
        # Sin ninguna nota todavía no se puede concluir nada por nota.
        requerida = None
    inasistencia = porcentaje(horas_ausentes, horas_totales) or Decimal("0")
    ritmo = porcentaje(horas_ausentes, horas_dictadas)

    perdida = requerida is not None and requerida > NOTA_MAXIMA_ESCALA
    if requerida is None and peso_restante <= 0 and acumulada is not None:
        perdida = acumulada < umbrales.nota_aprobacion
    aprobada = (requerida is not None and requerida <= NOTA_MINIMA_ESCALA) or (
        requerida is None
        and peso_restante <= 0
        and acumulada is not None
        and acumulada >= umbrales.nota_aprobacion
    )

    roja_nota = (nota_corte is not None and nota_corte < umbrales.nota_aprobacion) or (
        requerida is not None and requerida > NOTA_MAXIMA_ESCALA
    )
    roja_inasistencia = inasistencia > umbrales.limite_perdida_inasistencia
    amarilla_nota = (
        nota_corte is not None
        and umbrales.nota_amarilla_minima <= nota_corte <= umbrales.nota_amarilla_maxima
    )
    amarilla_inasistencia = inasistencia >= umbrales.umbral_amarillo_inasistencia or (
        ritmo is not None and ritmo >= umbrales.umbral_amarillo_inasistencia
    )

    if roja_nota or roja_inasistencia:
        estado = ESTADO_ROJA
    elif amarilla_nota or amarilla_inasistencia:
        estado = ESTADO_AMARILLA
    else:
        estado = ESTADO_VERDE
    motivo_nota = estado != ESTADO_VERDE and (roja_nota or amarilla_nota)
    motivo_inasistencia = estado != ESTADO_VERDE and (
        roja_inasistencia or amarilla_inasistencia
    )
    return ResultadoAlerta(
        estado=estado,
        motivo_nota=motivo_nota,
        motivo_inasistencia=motivo_inasistencia,
        nota_corte=nota_corte,
        nota_acumulada=acumulada,
        nota_requerida=requerida,
        porcentaje_inasistencia=inasistencia,
        porcentaje_ritmo=ritmo,
        perdida_por_nota=perdida,
        aprobada_por_nota=aprobada,
    )
