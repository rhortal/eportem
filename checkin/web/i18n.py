"""English and Spanish for the web UI. Keys are the English text; a missing
Spanish entry falls back to English, so nothing ever shows a raw key."""

ES = {
    "Today": "Hoy", "Schedule": "Horario", "Calendar": "Calendario", "Notifications": "Avisos",
    "ePortem account": "Cuenta de ePortem", "History": "Historial", "API tokens": "Tokens de API",
    "Profile": "Perfil", "Admin": "Administración", "Sign out": "Salir", "Sign in": "Entrar",
    "Username": "Usuario", "Password": "Contraseña", "Save": "Guardar", "Delete": "Borrar", "Add": "Añadir",
    "home": "casa", "office": "oficina", "Home": "Casa", "Office": "Oficina",
    "This week": "Esta semana", "Next week": "Semana que viene", "Today's runs": "Fichajes de hoy",
    "Nothing planned today": "Hoy no hay nada previsto", "Tap a day to switch home/office for that day only.":
        "Pulsa un día para cambiar casa/oficina solo ese día.",
    "Monday": "Lunes", "Tuesday": "Martes", "Wednesday": "Miércoles", "Thursday": "Jueves",
    "Friday": "Viernes", "Saturday": "Sábado", "Sunday": "Domingo",
    "Day off": "Libre", "Holiday": "Festivo", "Paused": "En pausa", "Inactive": "Inactivo",
    "lunch": "comida", "no lunch break": "sin pausa para comer",
    "January": "enero", "February": "febrero", "March": "marzo", "April": "abril", "May": "mayo",
    "June": "junio", "July": "julio", "August": "agosto", "September": "septiembre", "October": "octubre",
    "November": "noviembre", "December": "diciembre",
    "European day, 9–18": "Jornada europea, 9–18", "Spanish day, 9–18": "Jornada española, 9–18",
    "Spanish day, short Friday": "Jornada española, viernes corto",
    "Summer hours (jornada intensiva)": "Jornada intensiva de verano", "Continuous day": "Jornada continua",
    "Part-time mornings": "Media jornada de mañana",
    "9:00 to 18:00 with lunch 13:30–14:30, Monday to Friday":
        "De 9:00 a 18:00 con comida de 13:30 a 14:30, de lunes a viernes",
    "9:00 to 18:00 with lunch 14:30–15:30, Monday to Friday":
        "De 9:00 a 18:00 con comida de 14:30 a 15:30, de lunes a viernes",
    "Monday to Thursday 9:00 to 18:00 with lunch 14:30–15:30; Friday 8:00 to 15:00":
        "De lunes a jueves de 9:00 a 18:00 con comida de 14:30 a 15:30; viernes de 8:00 a 15:00",
    "8:00 to 15:00 with no lunch break, Monday to Friday": "De 8:00 a 15:00 sin pausa, de lunes a viernes",
    "8:00 to 16:00 with no lunch break, Monday to Friday": "De 8:00 a 16:00 sin pausa, de lunes a viernes",
    "9:00 to 14:00, Monday to Friday": "De 9:00 a 14:00, de lunes a viernes",
    "start_day": "Entrada", "lunch_break": "Comida", "after_lunch": "Vuelta",
    "stop_day": "Salida", "planned": "previsto", "running": "en curso", "recorded": "fichado",
    "not_recorded": "no fichado", "unknown": "desconocido", "skipped": "omitido", "failed": "fallido",
    "cancelled": "cancelado", "dry_run": "simulado",
    "Working-day template": "Plantilla de jornada", "Use this template": "Usar esta plantilla",
    "In use": "En uso", "Home days": "Días en casa", "Alternate two weeks": "Alternar dos semanas",
    "Public holidays": "Festivos", "Region": "Comunidad", "Periods": "Periodos",
    "Use another template for a date range, e.g. summer hours.":
        "Usar otra plantilla en unas fechas, por ejemplo la jornada intensiva.",
    "Every year": "Cada año", "From": "Desde", "To": "Hasta", "Label": "Etiqueta",
    "Time off": "Vacaciones", "Business trip": "Viaje de trabajo", "Location": "Lugar",
    "Other times": "Otro horario", "Work on a public holiday": "Trabajar un festivo", "Note": "Nota",
    "Changes": "Cambios", "Add a change": "Añadir un cambio",
    "Start": "Entrada", "Stop": "Salida", "Lunch out": "Salida a comer", "Lunch back": "Vuelta de comer",
    "Verify (logs in, never clocks)": "Comprobar (entra, nunca ficha)", "Activity IDs": "IDs de actividad",
    "Use direct HTTP (faster; the browser only logs in)": "Usar HTTP directo (más rápido; el navegador solo entra)",
    "Send a test": "Enviar prueba", "Clock notifications": "Avisos de fichaje", "Failure alerts": "Alertas de fallo",
    "Slack status": "Estado de Slack", "Random offset": "Margen aleatorio",
    "minutes before": "minutos antes", "minutes after": "minutos después", "Time zone": "Zona horaria",
    "Language": "Idioma", "Paused (nothing is clocked)": "En pausa (no se ficha nada)",
    "Change password": "Cambiar contraseña", "Current password": "Contraseña actual",
    "New password": "Contraseña nueva", "Saved.": "Guardado.", "Set up": "Configurar",
    "Get started": "Primeros pasos", "Next": "Siguiente", "Done": "Hecho", "Users": "Usuarios",
    "Runs that need a look": "Fichajes que revisar", "Log": "Registro", "Name": "Nombre",
    "Scopes": "Permisos", "Expires in days": "Caduca en días", "Create token": "Crear token",
    "Copy it now: it is not shown again.": "Cópialo ahora: no se vuelve a mostrar.", "Revoke": "Revocar",
    "Clock now": "Fichar ahora", "Wrong username or password.": "Usuario o contraseña incorrectos.",
    "Too many attempts; wait a few minutes.": "Demasiados intentos; espera unos minutos.",
    "The page expired; try again.": "La página caducó; inténtalo de nuevo.",
}

TRANSLATIONS = {"en": {}, "es": ES}


def pick_locale(user, accept_language, default):
    if user is not None and user.locale in TRANSLATIONS:
        return user.locale
    for part in (accept_language or "").split(","):
        code = part.split(";")[0].strip()[:2].lower()
        if code in TRANSLATIONS:
            return code
    return default


def translator(locale):
    table = TRANSLATIONS.get(locale, {})

    def t(text, **kw):
        out = table.get(text, text)
        return out.format(**kw) if kw else out
    return t
