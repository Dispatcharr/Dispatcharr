from django.views import View
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render

from .models import Stream

@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required, name='dispatch')
class StreamDashboardView(View):
    """
    Example “dashboard” style view for Streams
    """
    def get(self, request, *args, **kwargs):
        streams = Stream.objects.values(
            'id', 'name', 'url',
            'channel_group', 'current_viewers'
        )
        return JsonResponse({'data': list(streams)}, safe=False)

    def post(self, request, *args, **kwargs):
        """
        Creates a new Stream from JSON data
        """
        import json
        try:
            data = json.loads(request.body)
            new_stream = Stream.objects.create(**data)
            return JsonResponse({
                'id': new_stream.id,
                'message': 'Stream created successfully!'
            }, status=201)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)


@login_required
def channels_dashboard_view(request):
    return render(request, 'channels/channels.html')
