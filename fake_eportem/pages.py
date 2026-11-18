"""HTML for the fake: the login form and the clock dashboard in each state."""
import html

CAPTCHA_ERROR = "No se ha podido verificar que no es un robot. Recargue la página e inténtelo de nuevo."

# Absence types every dashboard offers (from the 2026-11-16 captures), besides
# the account's own work and lunch activities.
OTHER_PAUSES = [("3", "Ausencia"), ("5916", "Vacaciones")]

LABELS = {"not_started": "Iniciar", "stopped": "Iniciar", "working": "Pausar", "paused": "Reanudar"}


def login_page(recaptcha, error=None):
    script = ('<script src="/_fake/recaptcha/api.js?render=fake-site-key"></script>'
              if recaptcha else "")
    message = f'<div class="alert alert-danger">{html.escape(error)}</div>' if error else ""
    fill_token = ("<script>grecaptcha.ready(function () { grecaptcha.execute('fake-site-key', "
                  "{action: 'login'}).then(function (t) { document.getElementById('recaptchaToken').value = t; "
                  "}); });</script>") if recaptcha else ""
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"><title>ePortem - Login</title>{script}</head>
<body>
{message}
<form method="post" id="login-form">
  <input type="hidden" name="cc" value="false">
  <input type="hidden" name="recaptchaToken" id="recaptchaToken" value="">
  <input type="text" name="usuario" onblur="this.value = this.value.toUpperCase()">
  <input type="password" name="password">
  <label><input type="checkbox" name="recordar" value="true"> Recordar</label>
  <button type="submit" id="submit">Entrar</button>
</form>
{fill_token}
</body></html>"""


RECAPTCHA_JS = """var grecaptcha = {
  ready: function (cb) { cb(); },
  execute: function () { return Promise.resolve('fake-recaptcha-token'); }
};"""

# The real page sends the clock request from _doPostJor(this) (reghorjor1.3.js).
# Here it is a synchronous request, so a Selenium click returns only once the
# event is recorded.
CLOCK_JS = """function _send(id, name, kind, label) {
  var q = 'action=' + encodeURIComponent(id) +
          '&_codactiv=' + encodeURIComponent(name || '') +
          '&_tipoactiv=' + encodeURIComponent(kind || '') +
          '&_descactiv=' + encodeURIComponent(label || '') +
          '&_geolocation=&_localip=';
  var x = new XMLHttpRequest();
  x.open('GET', 'reghorario.cshtml?' + q, false);
  x.send();
  location.reload();
}
function _doPostJor(el) {
  _send(el.id, el.getAttribute('name'), el.getAttribute('name2'), el.getAttribute('name3'));
}"""


def _entry(id_, name, kind, label):
    name_attr = f' name="{html.escape(name)}"' if name is not None else ""
    return (f'<li><a href="#" id="{id_}"{name_attr} name2="{kind}" name3="{html.escape(label)}" '
            f'onclick="_doPostJor(this); return false;">{html.escape(label)}</a></li>')


def buttons_for(state, account):
    """[(id, name, kind, label)] offered in this state, in page order."""
    ids = account.activity_ids
    office = (ids.office, "W", "Trabajo")
    home = (ids.home, "W", "Trabajo en Casa")
    lunch = (ids.lunch_pause, "P", "Comida")
    pauses = [lunch] + [(n, "P", label) for n, label in OTHER_PAUSES]
    if state in ("not_started", "stopped"):
        return [("_ststart", *a) for a in (office, home, *pauses)]
    if state == "working":
        other_place = home if account.working_activity == ids.office else office
        return ([("_stpause", *p) for p in pauses] + [("_stini", *other_place)]
                + [("_ststop", None, "P", "Inicio Trabajo")])
    if state == "paused":
        return ([("_stini", *office), ("_stini", *home)] + [("_stpause", *p) for p in pauses[1:]]
                + [("_ststop", None, "P", "Inicio Trabajo")])
    raise ValueError(state)


def dashboard_page(state, account):
    """The clock box. Its layout is what the Selenium XPaths expect:
    #buttonsRegBox/div/div/button is the main button (its label is the state;
    with nothing started it starts work at the office), .../button/div/div[2]/h2
    holds the label, #buttonsRegBox/div/button[@data-toggle] opens the list of
    activities. The list is always rendered, so no CSS is needed to click it."""
    label = LABELS[state]
    main_click = ""
    if state in ("not_started", "stopped"):
        office = html.escape(account.activity_ids.office)
        main_click = f''' onclick="_send('_ststart', '{office}', 'W', 'Trabajo')"'''
    entries = "\n".join(_entry(*b) for b in buttons_for(state, account))
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"><title>ePortem - Registro</title>
<script>{CLOCK_JS}</script></head>
<body class="pace-done skin-1 fixed-sidebar">
<div id="wrapper"><div id="page-wrapper"><div class="wrapper wrapper-content"><div class="row">
<div class="col-lg-6 col-sm-12"><div class="ibox"><div class="ibox-content"><div class="row">
<div id="buttonsRegBox">
  <div class="btn-group">
    <div class="btn-group">
      <button class="btn btn-outline btn-block btn-primary" type="button"{main_click}>
        <div><div class="icon"></div><div><h2>{label}</h2></div></div>
      </button>
    </div>
    <button class="btn btn-primary dropdown-toggle" type="button" data-toggle="dropdown">&#9662;</button>
    <ul class="dropdown-menu">
{entries}
    </ul>
  </div>
</div>
</div></div></div></div>
</div></div></div></div>
</body></html>"""


def maintenance_page():
    return """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><title>Mantenimiento</title></head>
<body><h1>Estamos realizando tareas de mantenimiento</h1></body></html>"""
