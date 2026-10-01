from dialer import bp


@bp.route("/")
def home():
    return "dialer home (building)"
