FROM python:3.12-slim

# Create a non-root user for Hugging Face (UID 1000)
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

WORKDIR /app

# Copy requirements and install
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --upgrade -r requirements.txt

# Copy the rest of the app
COPY --chown=user . .

# Hugging Face Spaces use port 7860
EXPOSE 7860

ENV PYTHONUNBUFFERED=1

# Add backend to Python path and start the server
ENV PYTHONPATH="/app:$PYTHONPATH"
CMD gunicorn -w 4 -k uvicorn.workers.UvicornWorker backend.api.app:app --bind 0.0.0.0:7860
