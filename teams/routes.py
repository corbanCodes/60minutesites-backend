from teams import bp


@bp.route("/")
def team_home():
    return "team home (building)"


def join_invite(token):
    return "join (building)"
