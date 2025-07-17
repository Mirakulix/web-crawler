#!/bin/bash
sudo apt-get update
echo "Installing Text and PDF dependencies for Ubuntu with apt"
sudo apt-get install libpango-1.0-0 libharfbuzz0b libpangoft2-1.0-0 libffi-dev libcairo2 libcairo2-dev
echo "Installing o dependencies forv Ubuntu with apt"
sudo apt-get install ffmpeg chromium-chromedriver
echo "Installation completed!"

if [ -d "venv" ]; then
	source venv/bin/activate
elif [ -d ".venv" ]; then
	source .venv/bin/activate
else
	python3 -m venv venv
	source venv/bin/activate
fi

pip install -r requirements.txt

