# This will be the main file for the HLS proxy.
# It will handle fetching the HLS manifest, modifying it, and serving it to the client.
# It will also handle fetching the HLS segments and serving them to the client.

import flask
import requests
import logging

app = flask.Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.DEBUG)

@app.route('/proxy/<path:url>')
def proxy(url):
    try:
        # Fetch the HLS manifest from the target URL.
        logging.debug(f"Fetching manifest from: {url}")
        response = requests.get(url)
        response.raise_for_status()  # Raise an exception for bad status codes

        # Modify the manifest to point to our proxy.
        manifest_content = response.text
        modified_manifest = []
        for line in manifest_content.splitlines():
            if line.startswith('#') or not line.strip():
                modified_manifest.append(line)
            else:
                modified_manifest.append(f"/segment/{line.strip()}")

        logging.debug(f"Serving modified manifest for: {url}")
        # Serve the modified manifest to the client.
        return flask.Response('\n'.join(modified_manifest), mimetype='application/vnd.apple.mpegurl')
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching manifest: {e}")
        return flask.Response(f"Error fetching manifest: {e}", status=500)
    except Exception as e:
        logging.error(f"An unexpected error occurred in proxy: {e}")
        return flask.Response(f"An unexpected error occurred: {e}", status=500)

@app.route('/segment/<path:url>')
def segment(url):
    try:
        # Fetch the HLS segment from the target URL.
        logging.debug(f"Fetching segment from: {url}")
        response = requests.get(url, stream=True)
        response.raise_for_status()  # Raise an exception for bad status codes

        # Serve the segment to the client.
        logging.debug(f"Serving segment for: {url}")
        return flask.Response(
            flask.stream_with_context(response.iter_content(chunk_size=1024)),
            content_type=response.headers['Content-Type']
        )
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching segment: {e}")
        return flask.Response(f"Error fetching segment: {e}", status=500)
    except Exception as e:
        logging.error(f"An unexpected error occurred in segment: {e}")
        return flask.Response(f"An unexpected error occurred: {e}", status=500)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
