#!/bin/bash

# Install dependencies
pip install -r requirements.txt

# Run the HLS proxy
python hls_proxy.py
