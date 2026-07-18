# core/views.py
from django.shortcuts import render


def settings_view(request):
    """
    Renders the settings page.
    """
    return render(request, 'settings.html')
