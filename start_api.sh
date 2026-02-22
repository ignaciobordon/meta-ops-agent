#!/bin/bash
# Start the API server with correct PYTHONPATH

export PYTHONPATH="$(pwd):$(pwd)/backend:$PYTHONPATH"
cd backend && python main.py
