
def navigation(request):
    nav_items = [
        {'name':'Dashboard', 'icon':'bi:speedometer', 'url': 'dashboard:dashboard'},
        {'name':'Channels', 'icon':'bi:tv', 'url': 'channels:channels_dashboard'},
        {'name':'M3U', 'icon':'bi:file-earmark-text', 'url': 'm3u:m3u_dashboard'},
        {'name':'EPG', 'icon':'bi:calendar3', 'url': 'epg:epg_dashboard'},
        {'name':'Settings', 'icon':'bi:gear', 'url': 'dashboard:settings'},
    ]
    return {'nav_items': nav_items}

def ui_theme(request):
    themeCookie = request.COOKIES.get('bs-theme', 'light')
    navCookie = request.COOKIES.get('nav-open', 'false')
    return {
        'appTheme': themeCookie,
        'appNavOpen': navCookie,
    }

