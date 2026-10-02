web: gunicorn app:app -k gthread -w 2 --threads 8 --timeout 60 --bind 0.0.0.0:$PORT
worker: python worker.py
