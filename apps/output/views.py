from django.http import HttpResponse
from django.urls import reverse
from apps.channels.models import Channel
from apps.epg.models import ProgramData
from django.utils import timezone

def generate_m3u(request):
    """
    Dynamically generate an M3U file from channels.
    The stream URL now points to the new stream_view that uses StreamProfile.
    """
    m3u_content = "#EXTM3U\n"
    channels = Channel.objects.order_by('channel_number')
    for channel in channels:
        group_title = channel.channel_group.name if channel.channel_group else "Default"
        tvg_id = channel.tvg_id or ""
        tvg_name = channel.tvg_name or channel.channel_name
        tvg_logo = channel.logo_url or ""
        channel_number = channel.channel_number

        extinf_line = (
            f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{tvg_name}" tvg-logo="{tvg_logo}" '
            f'tvg-chno="{channel_number}" group-title="{group_title}",{channel.channel_name}\n'
        )
        stream_url = request.build_absolute_uri(reverse('output:stream', args=[channel_number]))
        m3u_content += extinf_line + stream_url + "\n"

    response = HttpResponse(m3u_content, content_type="application/x-mpegURL")
    response['Content-Disposition'] = 'attachment; filename="channels.m3u"'
    return response

def generate_epg(request):
    """
    Dynamically generate an XMLTV (EPG) file using the new EPGData/ProgramData models.
    Since the EPG data is stored independently of Channels, we group programmes
    by their associated EPGData record.
    This version does not filter by time, so it includes the entire EPG saved in the DB.
    """
    # Retrieve all ProgramData records and join the related EPGData record.
    programs = ProgramData.objects.select_related('epg').all().order_by('start_time')

    # Group programmes by their EPGData record.
    epg_programs = {}
    for prog in programs:
        epg = prog.epg
        epg_programs.setdefault(epg, []).append(prog)

    xml_lines = []
    xml_lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    xml_lines.append('<tv generator-info-name="Dispatcharr" generator-info-url="https://example.com">')
    
    # Output channel definitions based on EPGData.
    # Use the EPGData's tvg_id (or a fallback) as the channel identifier.
    for epg in epg_programs.keys():
        channel_id = epg.tvg_id if epg.tvg_id else f"default-{epg.id}"
        xml_lines.append(f'  <channel id="{channel_id}">')
        xml_lines.append(f'    <display-name>{epg.channel_name}</display-name>')
        xml_lines.append('  </channel>')
    
    # Output programme entries referencing the channel id from EPGData.
    for epg, progs in epg_programs.items():
        channel_id = epg.tvg_id if epg.tvg_id else f"default-{epg.id}"
        for prog in progs:
            start_str = prog.start_time.strftime("%Y%m%d%H%M%S %z")
            stop_str = prog.end_time.strftime("%Y%m%d%H%M%S %z")
            xml_lines.append(f'  <programme start="{start_str}" stop="{stop_str}" channel="{channel_id}">')
            xml_lines.append(f'    <title>{prog.title}</title>')
            xml_lines.append(f'    <desc>{prog.description}</desc>')
            xml_lines.append('  </programme>')
    
    xml_lines.append('</tv>')
    xml_content = "\n".join(xml_lines)

    response = HttpResponse(xml_content, content_type="application/xml")
    response['Content-Disposition'] = 'attachment; filename="epg.xml"'
    return response
