# Definición de procesos técnicos de PLASEA

Referencia: IEEE Std 1058-1998, §6 (procesos técnicos). La jerarquía del repositorio sigue la definida en este plan. Cualquier carpeta nueva, movida o eliminada se actualiza primero aquí.

## 1. Herramientas y entornos
- IDE unificado: Visual Studio Code. Sistema operativo de desarrollo: Windows (comandos en PowerShell).
- Navegadores de verificación: Chrome y Edge actuales.
- Control de versiones: GitHub con GitFlow. Gestión de tareas: Jira. Cronograma: GanttProject.

## 2. Lenguajes y frameworks
- Backend: Python + Flask (monolito con plantillas Jinja2, un blueprint por épica), SQLAlchemy y migraciones.
- Frontend: JavaScript vanilla + Bootstrap, servidos desde archivos locales.
- Base de datos: MariaDB (XAMPP), codificación utf8mb4.

## 3. Gestión de configuración
- Ramas: `main`, `develop`, `feature/RF-xx-descripcion`, `release/entrega-*`, `hotfix/*`.
- Fusiones por pull request con revisión de código. Cada entrega se etiqueta en `main`.
- Los commits citan el RF. Sin secretos en el repositorio (`.env` excluido; `.env.example` como guía).

## 4. Convenciones de codificación
- Python: PEP 8, PEP 257 (docstrings en español) y PEP 484. Black, flake8 y pytest con configuración compartida (`pyproject.toml`, `.flake8`).
- Nombres en español, sin tildes ni ñ: snake_case (funciones, variables, tablas, columnas), PascalCase (clases), MAYUSCULAS_CON_GUION_BAJO (constantes).
- JavaScript: ES2015 o superior, `const`/`let`, igualdad estricta, camelCase.
- HTML5 semántico; CSS con variables (tokens de diseño).

## 5. Metodologías de documentación
- Requisitos: ISO/IEC/IEEE 29148 con estructura IEEE 830.
- Arquitectura: ISO/IEC/IEEE 42010 (versión breve).
- Pruebas: IEEE 1012 (versión breve).
- Citas: APA 7.ª edición.

## 6. Jerarquía del repositorio
```
plasea/
├── 00-gestion/        Acta, definición de procesos técnicos, riesgos y control
├── 01-requisitos/     Etapa de requisitos (especificacion/, trazabilidad/)
├── 02-arquitectura/   Etapa de diseño (solucion-logica/, modelo-datos/, decisiones/)
├── 03-construccion/   Etapa de codificación (logica-negocio/, interfaz/, scripts/)
├── 04-pruebas/        Verificación y validación (unitarias/, seguridad/, funcionales/, casos-de-prueba/)
└── 05-manuales/       Manual técnico y manuales de usuario por rol
```
Flask usa `03-construccion/interfaz` como `template_folder` y `static_folder`. El paquete `plasea` vive en `03-construccion/logica-negocio`, que se agrega al PYTHONPATH y a la configuración de pytest.
